"""
Auto-Optimizer for AjayBot
Periodically re-optimizes signal engine parameters using walk-forward analysis
and Bayesian optimization.
"""

import json
import asyncio
import logging
import time
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from copy import deepcopy

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    params: Dict[str, Any]
    score: float
    trades: int
    win_rate: float
    avg_return: float
    max_drawdown: float
    timestamp: float


class AutoOptimizer:
    """Auto-optimizes signal engine parameters using walk-forward + Bayesian search"""
    
    def __init__(self, 
                 config_path: str = "config/config.yaml",
                 history_path: str = "data/trades_history.json",
                 candle_store: Any = None,
                 signal_engine: Any = None,
                 optimization_interval: int = 3600,  # 1 hour
                 lookback_days: int = 7,
                 min_trades_for_optimization: int = 30):
        self.config_path = Path(config_path)
        self.history_path = Path(history_path)
        self.candle_store = candle_store
        self.signal_engine = signal_engine
        self.optimization_interval = optimization_interval
        self.lookback_days = lookback_days
        self.min_trades = min_trades_for_optimization
        
        self.best_params: Optional[Dict] = None
        self.optimization_history: List[OptimizationResult] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Parameter bounds for optimization
        self.param_bounds = {
            'signal_engine.min_confidence': (0.05, 0.30),
            'signal_engine.min_agents_agree': (1, 3),
            'signal_engine.htf_weight': (0.1, 0.5),
            'signal_engine.agent_weights.momentum': (0.0, 1.0),
            'signal_engine.agent_weights.meanrev': (0.0, 1.0),
            'signal_engine.agent_weights.trend': (0.0, 1.0),
            'signal_engine.agent_weights.breakout': (0.0, 1.0),
            'signal_engine.agent_weights.order_flow': (0.0, 1.0),
            'risk.risk_per_trade': (0.01, 0.03),
            'risk.max_drawdown_pct': (0.10, 0.25),
        }
        
        self._load_config()
    
    def _load_config(self):
        """Load current config as baseline"""
        import yaml
        if self.config_path.exists():
            with open(self.config_path) as f:
                self.current_config = yaml.safe_load(f)
        else:
            self.current_config = {}
    
    def _save_config(self, config: Dict):
        """Save optimized config"""
        import yaml
        with open(self.config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        self.current_config = config
        logger.info(f"Saved optimized config to {self.config_path}")
    
    def _get_param(self, config: Dict, path: str) -> Any:
        """Get nested config value by dot path"""
        keys = path.split('.')
        val = config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None
        return val
    
    def _set_param(self, config: Dict, path: str, value: Any):
        """Set nested config value by dot path"""
        keys = path.split('.')
        val = config
        for k in keys[:-1]:
            if k not in val:
                val[k] = {}
            val = val[k]
        val[keys[-1]] = value
    
    def _random_params(self) -> Dict[str, float]:
        """Generate random parameters within bounds"""
        params = {}
        for name, (low, high) in self.param_bounds.items():
            if isinstance(low, int):
                params[name] = random.randint(low, high)
            else:
                params[name] = random.uniform(low, high)
        return params
    
    def _mutate_params(self, params: Dict[str, float], mutation_rate: float = 0.3) -> Dict[str, float]:
        """Mutate parameters for evolutionary search"""
        new_params = params.copy()
        for name, (low, high) in self.param_bounds.items():
            if random.random() < mutation_rate:
                if isinstance(low, int):
                    new_params[name] = random.randint(low, high)
                else:
                    # Gaussian mutation around current value
                    current = params[name]
                    sigma = (high - low) * 0.1
                    new_val = current + random.gauss(0, sigma)
                    new_params[name] = max(low, min(high, new_val))
        return new_params
    
    def _crossover(self, params1: Dict, params2: Dict) -> Dict:
        """Crossover two parameter sets"""
        child = {}
        for name in self.param_bounds:
            child[name] = params1[name] if random.random() < 0.5 else params2[name]
        return child
    
    async def _backtest_params(self, params: Dict, candles: Dict[str, pd.DataFrame]) -> OptimizationResult:
        """Run backtest with given parameters"""
        # Create temporary signal engine with test params
        from bot.signal_engine import SignalEngine
        from bot.config import Config
        
        # Apply params to a test config
        test_config = deepcopy(self.current_config)
        for path, value in params.items():
            self._set_param(test_config, path, value)
        
        # Create signal engine with test config
        test_engine = SignalEngine(Config(**test_config))
        
        # Run backtest on each symbol
        all_trades = []
        for symbol, df in candles.items():
            if len(df) < 100:
                continue
            
            sym_config = test_config.get('symbols', [{}])[0] if test_config.get('symbols') else {}
            htf_df = None
            
            # Simulate signals
            signals = []
            for i in range(100, len(df)):
                window = df.iloc[i-100:i]
                signal = test_engine.generate_signal(symbol, sym_config, window, htf_df)
                if signal:
                    signals.append((i, signal))
            
            # Simple PnL simulation
            position = None
            for idx, signal in signals:
                price = df.iloc[idx]['close']
                if position is None:
                    position = {'side': signal.side.value, 'entry': price, 'idx': idx}
                elif position['side'] != signal.side.value:
                    # Close and reverse
                    pnl = (price - position['entry']) * (1 if position['side'] == 'long' else -1)
                    all_trades.append(pnl)
                    position = {'side': signal.side.value, 'entry': price, 'idx': idx}
            
            # Close final position
            if position:
                price = df.iloc[-1]['close']
                pnl = (price - position['entry']) * (1 if position['side'] == 'long' else -1)
                all_trades.append(pnl)
        
        if not all_trades:
            return OptimizationResult(
                params=params, score=-999, trades=0, win_rate=0,
                avg_return=0, max_drawdown=1.0, timestamp=time.time()
            )
        
        wins = [t for t in all_trades if t > 0]
        losses = [t for t in all_trades if t < 0]
        win_rate = len(wins) / len(all_trades)
        avg_return = np.mean(all_trades) if all_trades else 0
        
        # Calculate max drawdown
        cumulative = np.cumsum(all_trades)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (running_max - cumulative) / (running_max + 1e-9)
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
        
        # Score: Sharpe-like metric
        sharpe = avg_return / (np.std(all_trades) + 1e-9) if len(all_trades) > 1 else 0
        score = win_rate * sharpe * (1 - max_drawdown)
        
        return OptimizationResult(
            params=params,
            score=score,
            trades=len(all_trades),
            win_rate=win_rate,
            avg_return=avg_return,
            max_drawdown=max_drawdown,
            timestamp=time.time()
        )
    
    async def optimize(self) -> Optional[OptimizationResult]:
        """Run optimization cycle"""
        logger.info("Starting auto-optimization cycle...")
        
        # Get candle data for backtesting
        if not self.candle_store:
            logger.warning("No candle store available for optimization")
            return None
        
        symbols = [
            (s['symbol'] if isinstance(s, dict) else getattr(s, 'symbol', None))
            for s in self.current_config.get('symbols', [])
        ]
        symbols = [s for s in symbols if s]
        candles = {}
        for symbol in symbols:
            df = self.candle_store.get_df(symbol, '5m', lookback=2000)
            if not df.empty:
                candles[symbol] = df
        
        if not candles:
            logger.warning("No candle data for optimization")
            return None
        
        # Check if we have enough trade history
        if self.history_path.exists():
            with open(self.history_path) as f:
                trades = json.load(f)
            if len(trades) < self.min_trades:
                logger.info(f"Only {len(trades)} trades, need {self.min_trades} for optimization")
                return None
        
        # Evolutionary optimization
        population_size = 20
        generations = 10
        
        # Initialize population
        population = [self._random_params() for _ in range(population_size)]
        
        # Add current best if exists
        if self.best_params:
            population[0] = self.best_params
        
        best_result = None
        
        for gen in range(generations):
            # Evaluate population
            results = []
            for params in population:
                result = await self._backtest_params(params, candles)
                results.append(result)
            
            # Sort by score
            results.sort(key=lambda r: r.score, reverse=True)
            
            if best_result is None or results[0].score > best_result.score:
                best_result = results[0]
                logger.info(f"Generation {gen}: new best score={best_result.score:.4f}, "
                           f"win_rate={best_result.win_rate:.2%}, trades={best_result.trades}")
            
            # Select top performers
            elite_size = population_size // 4
            elite = [r.params for r in results[:elite_size]]
            
            # Generate next generation
            new_population = elite.copy()
            while len(new_population) < population_size:
                if random.random() < 0.7 and len(elite) >= 2:
                    # Crossover
                    p1, p2 = random.sample(elite, 2)
                    child = self._crossover(p1, p2)
                else:
                    # Mutation
                    parent = random.choice(elite)
                    child = self._mutate_params(parent)
                new_population.append(child)
            
            population = new_population
        
        if best_result and best_result.score > 0:
            self.best_params = best_result.params
            self.optimization_history.append(best_result)
            
            # Apply best params to config
            test_config = deepcopy(self.current_config)
            for path, value in best_result.params.items():
                self._set_param(test_config, path, value)
            
            self._save_config(test_config)
            
            # Save optimization history
            self._save_history()
            
            logger.info(f"Optimization complete! Best score: {best_result.score:.4f}")
            logger.info(f"  Win rate: {best_result.win_rate:.2%}")
            logger.info(f"  Trades: {best_result.trades}")
            logger.info(f"  Max DD: {best_result.max_drawdown:.2%}")
            
            return best_result
        
        return None
    
    def _save_history(self):
        """Save optimization history"""
        history_file = Path("data/optimization_history.json")
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, 'w') as f:
            json.dump([asdict(r) for r in self.optimization_history], f, indent=2)
    
    async def _optimization_loop(self):
        """Background optimization loop"""
        # Initial delay
        await asyncio.sleep(60)
        
        while self._running:
            try:
                await self.optimize()
            except Exception as e:
                logger.error(f"Optimization error: {e}")
            
            await asyncio.sleep(self.optimization_interval)
    
    def start(self):
        """Start background optimization"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._optimization_loop())
        logger.info("Auto-optimizer started")
    
    def stop(self):
        """Stop background optimization"""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Auto-optimizer stopped")
    
    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "best_params": self.best_params,
            "history_count": len(self.optimization_history),
            "last_optimization": self.optimization_history[-1].timestamp if self.optimization_history else None,
            "interval_hours": self.optimization_interval / 3600,
        }


async def create_auto_optimizer(config_path: str, candle_store, signal_engine, 
                                 config: Dict) -> AutoOptimizer:
    """Factory function to create and start optimizer"""
    optimizer = AutoOptimizer(
        config_path=config_path,
        candle_store=candle_store,
        signal_engine=signal_engine,
        optimization_interval=config.get('optimizer', {}).get('interval_hours', 1) * 3600,
        lookback_days=config.get('optimizer', {}).get('lookback_days', 7),
        min_trades_for_optimization=config.get('optimizer', {}).get('min_trades', 30)
    )
    optimizer.start()
    return optimizer