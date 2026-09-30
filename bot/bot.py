"""
Main Bot Engine - Paper trading with WebSocket feeds and persistence
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd

from .config import get_settings, get_symbol_config, Config
from .delta_client import DeltaClient, create_client, create_public_ws, Candle
from .indicators import all_indicators
from .signal_engine import SignalEngine, Signal, SignalSide
from .risk_manager import RiskManager, AdaptiveRiskManager, RiskAction
from .performance_tracker import PerformanceTracker, create_performance_tracker, TradeRecord, track_performance_loop
from .auto_optimizer import AutoOptimizer, create_auto_optimizer

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str
    size: float
    entry_price: float
    entry_time: int
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    contract_size: float = 1.0
    trail_price: Optional[float] = None
    breakeven: bool = False
    partial_filled: bool = False
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    regime: str = ""
    confidence: float = 0.0
    agents: Dict = None


class PaperEngine:
    """Paper trading execution engine"""
    
    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[DeltaClient] = None
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Dict] = {}
        self.order_id_counter = 0
        
    async def start(self):
        self.client = await create_client(self.config)
        logger.info("Paper engine started")
    
    async def stop(self):
        if self.client:
            await self.client.close()
    
    def _next_order_id(self) -> str:
        self.order_id_counter += 1
        return f"paper_{self.order_id_counter}_{int(time.time()*1000)}"
    
    async def place_order(self, symbol: str, side: str, size: float,
                         entry_price: float, stop_loss: float,
                         take_profit_1: float, take_profit_2: float) -> Optional[Dict]:
        """Simulate order placement"""
        order_id = self._next_order_id()
        
        # In paper mode, fill immediately at entry_price
        pos = Position(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            entry_time=int(time.time() * 1000),
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
        )
        
        self.positions[symbol] = pos
        self.orders[order_id] = {
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'size': size,
            'price': entry_price,
            'status': 'filled',
            'timestamp': int(time.time() * 1000)
        }
        
        logger.info(f"Paper order filled: {symbol} {side} {size} @ {entry_price}")
        return self.orders[order_id]
    
    async def update_positions(self, tickers: Dict[str, float]):
        """Update unrealized PnL from live prices"""
        for symbol, pos in self.positions.items():
            if symbol in tickers:
                mark = tickers[symbol]
                if pos.side == 'long':
                    pos.unrealized_pnl = (mark - pos.entry_price) * pos.size * pos.contract_size
                else:
                    pos.unrealized_pnl = (pos.entry_price - mark) * pos.size * pos.contract_size
    
    def check_exits(self, symbol: str, current_price: float) -> List[str]:
        """Check if position should be closed - returns most aggressive exit only"""
        if symbol not in self.positions:
            return []
        
        pos = self.positions[symbol]
        
        if pos.side == 'long':
            # Check stops first (most critical)
            if current_price <= pos.stop_loss:
                return ['stop_loss']
            if current_price >= pos.take_profit_2:
                return ['take_profit_2']
            if current_price >= pos.take_profit_1 and not pos.partial_filled:
                return ['take_profit_1']
        else:
            if current_price >= pos.stop_loss:
                return ['stop_loss']
            if current_price <= pos.take_profit_2:
                return ['take_profit_2']
            if current_price <= pos.take_profit_1 and not pos.partial_filled:
                return ['take_profit_1']
        
        # Trailing stop
        if pos.trail_price:
            if pos.side == 'long' and current_price <= pos.trail_price:
                return ['trail']
            elif pos.side == 'short' and current_price >= pos.trail_price:
                return ['trail']
        
        return []
    
    def close_position(self, symbol: str, price: float, reason: str) -> float:
        """Close position and return PnL"""
        if symbol not in self.positions:
            return 0.0
        
        pos = self.positions[symbol]
        
        if pos.side == 'long':
            pnl = (price - pos.entry_price) * pos.size * pos.contract_size
        else:
            pnl = (pos.entry_price - price) * pos.size * pos.contract_size
        
        pos.realized_pnl = pnl
        pos.unrealized_pnl = 0.0
        
        logger.info(f"Closed {symbol} {reason} @ {price}: PnL={pnl:.2f}")
        
        del self.positions[symbol]
        return pnl
    
    def partial_close(self, symbol: str, price: float, fraction: float) -> float:
        """Partial close at TP1"""
        if symbol not in self.positions:
            return 0.0
        
        pos = self.positions[symbol]
        close_size = pos.size * fraction
        
        if pos.side == 'long':
            pnl = (price - pos.entry_price) * close_size * pos.contract_size
        else:
            pnl = (pos.entry_price - price) * close_size * pos.contract_size
        
        pos.size -= close_size
        pos.partial_filled = True
        pos.realized_pnl += pnl
        
        logger.info(f"Partial close {symbol} {fraction*100:.0f}% @ {price}: PnL={pnl:.2f}")
        return pnl


class CandleStore:
    """In-memory candle cache with persistence"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.caches: Dict[str, Dict[str, pd.DataFrame]] = {}  # symbol -> resolution -> DataFrame
        self.max_candles = 1000
    
    def _key(self, symbol: str, resolution: str) -> str:
        return f"{symbol}_{resolution}"
    
    async def ensure_history(self, symbol: str, resolution: str, lookback: int, client: DeltaClient):
        """Ensure we have enough history"""
        key = self._key(symbol, resolution)
        if key in self.caches and len(self.caches[key]) >= lookback:
            return
        
        # Fetch from API
        end = int(time.time())
        start = end - (lookback * self._resolution_to_seconds(resolution))
        
        try:
            candles = await client.get_candles(symbol, resolution, start, end, limit=lookback)
            df = self._candles_to_df(candles)
            self.caches[key] = df
            logger.info(f"Loaded {len(df)} candles for {symbol} {resolution}")
        except Exception as e:
            logger.error(f"Failed to load candles for {symbol} {resolution}: {e}")
            if key not in self.caches:
                self.caches[key] = pd.DataFrame()
    
    def _resolution_to_seconds(self, res: str) -> int:
        mapping = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400}
        return mapping.get(res, 300)
    
    def _candles_to_df(self, candles: List[Candle]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame()
        data = [{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        } for c in candles]
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('timestamp', inplace=True)
        return df
    
    def add_candle(self, symbol: str, resolution: str, candle: Candle):
        """Add new candle to cache"""
        key = self._key(symbol, resolution)
        if key not in self.caches:
            self.caches[key] = pd.DataFrame()
        
        df = self.caches[key]
        new_row = pd.DataFrame([{
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume
        }], index=[pd.Timestamp(candle.timestamp, unit='s')])
        
        # Update or append
        if candle.timestamp in df.index:
            df.loc[candle.timestamp] = new_row.iloc[0]
        else:
            df = pd.concat([df, new_row])
        
        # Trim
        if len(df) > self.max_candles:
            df = df.iloc[-self.max_candles:]
        
        self.caches[key] = df
    
    def get_df(self, symbol: str, resolution: str, lookback: int = None) -> pd.DataFrame:
        """Get dataframe with indicators"""
        key = self._key(symbol, resolution)
        if key not in self.caches:
            return pd.DataFrame()
        
        df = self.caches[key].copy()
        if lookback and len(df) > lookback:
            df = df.iloc[-lookback:]
        return df
    
    def persist_all(self):
        """Save caches to disk"""
        for key, df in self.caches.items():
            if not df.empty:
                path = self.data_dir / f"candles_{key}.parquet"
                try:
                    df.to_parquet(path)
                except Exception as e:
                    logger.warning(f"Failed to persist {key}: {e}")


# Global instances
candle_store = CandleStore()
_bot_instance = None


class AjayBot:
    """Main trading bot"""
    
    def __init__(self, config: Config):
        self.config = config
        self.settings = config
        self.engine = PaperEngine(config)
        self.signal_engine = SignalEngine(config)
        self.risk_manager = RiskManager(config)
        self.adaptive_risk = AdaptiveRiskManager(config)
        # Performance tracker
        self.performance_tracker = create_performance_tracker(config.model_dump())
        # Auto optimizer
        self.auto_optimizer = AutoOptimizer(
            config_path="config/config.yaml",
            candle_store=candle_store,
            signal_engine=self.signal_engine,
            optimization_interval=config.optimizer.interval_hours * 3600,
            lookback_days=config.optimizer.lookback_days,
            min_trades_for_optimization=config.optimizer.min_trades
        )
        
        self._running = False
        self._positions: Dict[str, Position] = {}
        self._signal_history: List[Signal] = []
        self._consecutive_losses = 0
        self._daily_pnl = 0.0
        self._peak_equity = config.risk.paper_equity
        self._current_equity = config.risk.paper_equity
        self._start_time = time.time()
        self._heartbeat_time = time.time()
        self._poll_interval = 15
        self._ws_client = None
        self._ticker_ws = None
        self._main_task = None
        
        # State persistence
        self._state_file = Path(config.data_dir).absolute() / "bot_state.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        
        # Sync engine positions with our positions (single source of truth)
        self.engine.positions = self._positions
        
        # Lock to prevent double-close race
        self._position_lock = asyncio.Lock()
    
    def _load_state(self):
        """Load persisted state"""
        if self._state_file.exists():
            try:
                with open(self._state_file, 'r') as f:
                    state = json.load(f)
                self._current_equity = state.get('equity', self._current_equity)
                self._peak_equity = state.get('peak_equity', self._peak_equity)
                self._daily_pnl = state.get('daily_pnl', 0.0)
                self._consecutive_losses = state.get('consecutive_losses', 0)
                # Restore positions
                for sym, pos_data in state.get('positions', {}).items():
                    self._positions[sym] = Position(**pos_data)
                logger.info(f"Restored state: equity={self._current_equity:.2f}, positions={len(self._positions)}")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Persist state to disk"""
        try:
            state = {
                'equity': self._current_equity,
                'peak_equity': self._peak_equity,
                'daily_pnl': self._daily_pnl,
                'consecutive_losses': self._consecutive_losses,
                'positions': {sym: pos.__dict__ for sym, pos in self._positions.items()},
                'timestamp': time.time()
            }
            logger.info(f"Saving state to {self._state_file}: equity={self._current_equity:.2f}, positions={len(self._positions)}")
            with open(self._state_file, 'w') as f:
                json.dump(state, f)
            logger.info("State saved successfully")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    async def start(self):
        logger.info(f"Starting AjayBot in {self.config.mode} mode")

        await self.engine.start()

        # Initialize candle caches
        for sym_config in self.config.symbols:
            symbol = sym_config.symbol
            resolutions = [sym_config.resolution]
            if sym_config.htf_resolution:
                resolutions.append(sym_config.htf_resolution)

            for res in resolutions:
                await candle_store.ensure_history(symbol, res, sym_config.lookback, self.engine.client)

        # No WebSocket - use REST polling for everything (candles + tickers)
        self._ws_client = None
        self._ticker_ws = None

        self._running = True
        self._main_task = asyncio.create_task(self._main_loop())

        # Start performance tracking background task
        self._perf_task = asyncio.create_task(
            track_performance_loop(self.performance_tracker, interval=300)
        )

        # Start auto-optimizer
        self.auto_optimizer.start()

        logger.info("AjayBot started successfully (REST-only mode)")
        
        try:
            await self._main_task
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def _on_candle(self, symbol: str, resolution: str, candle_data: Dict):
        """Handle incoming candle"""
        candle = Candle(
            timestamp=candle_data['time'],
            open=candle_data['open'],
            high=candle_data['high'],
            low=candle_data['low'],
            close=candle_data['close'],
            volume=candle_data['volume']
        )
        candle_store.add_candle(symbol, resolution, candle)
    
    async def _on_ticker(self, ticker_data: Dict):
        """Handle ticker update for PnL and real-time exit checks"""
        symbol = ticker_data['symbol']
        mark_price = ticker_data['mark_price']
        
        # Update engine positions
        await self.engine.update_positions({symbol: mark_price})
        
        # Update our positions
        if symbol in self._positions:
            pos = self._positions[symbol]
            if pos.side == 'long':
                pos.unrealized_pnl = (mark_price - pos.entry_price) * pos.size * pos.contract_size
            else:
                pos.unrealized_pnl = (pos.entry_price - mark_price) * pos.size * pos.contract_size
            
            # Real-time exit check on ticker prices
            exits = self.engine.check_exits(symbol, mark_price)
            if exits:
                # Schedule position management immediately
                sym_config = get_symbol_config(symbol)
                if sym_config:
                    # Get latest candle data for ATR
                    df = candle_store.get_df(symbol, sym_config.resolution, lookback=sym_config.lookback)
                    await self._manage_position(symbol, sym_config, df)
    
    async def _main_loop(self):
        """Main trading loop"""
        while self._running:
            try:
                await self._process_cycle()
                self._save_state()
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)
    
    async def _process_cycle(self):
        """Process one trading cycle for all symbols"""
        # Daily reset check
        today = datetime.now(timezone.utc).date()
        if hasattr(self, '_last_reset_date') and today != self._last_reset_date:
            self.risk_manager.reset_daily(self._current_equity)
            self._daily_pnl = 0.0
            self._last_reset_date = today
        elif not hasattr(self, '_last_reset_date'):
            self._last_reset_date = today
        
        # Update equity from unrealized PnL
        total_unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        self._current_equity = self.config.risk.paper_equity + self._daily_pnl + total_unrealized
        self._peak_equity = max(self._peak_equity, self._current_equity)
        self._heartbeat_time = time.time()
        
        # REST API price polling for exit checks (fallback if WS ticker fails)
        if self._positions:
            try:
                symbols = list(self._positions.keys())
                logger.info(f"[REST_POLL] Polling for {symbols}")
                # Get tickers for our symbols only
                tickers = await self.engine.client.get_tickers(symbols)
                logger.info(f"[REST_POLL] Got {len(tickers)} tickers")
                
                # Build dict for fast lookup
                ticker_dict = {}
                for t in tickers:
                    sym = t.get('symbol')
                    if sym in symbols:
                        mark_price = t.get('mark_price')
                        if mark_price is not None:
                            ticker_dict[sym] = float(mark_price)
                
                for symbol, mark_price in ticker_dict.items():
                    logger.info(f"[REST_POLL] Ticker {symbol}: mark={mark_price}")
                    pos = self._positions[symbol]
                    if pos.side == 'long':
                        pos.unrealized_pnl = (mark_price - pos.entry_price) * pos.size * pos.contract_size
                    else:
                        pos.unrealized_pnl = (pos.entry_price - mark_price) * pos.size * pos.contract_size
                    logger.info(f"[REST_POLL] Position {symbol}: unrealized_pnl={pos.unrealized_pnl}")
                    
                    # Real-time exit check
                    exits = self.engine.check_exits(symbol, mark_price)
                    logger.info(f"[REST_POLL] Exits for {symbol} @ {mark_price}: {exits}")
                    if exits:
                        sym_config = get_symbol_config(symbol)
                        if sym_config:
                            df = candle_store.get_df(symbol, sym_config.resolution, lookback=sym_config.lookback)
                            # Add indicators for ATR/trail
                            df = all_indicators(df, sym_config.model_dump())
                            # Lock acquired inside _manage_position (single choke point)
                            await self._manage_position(symbol, sym_config, df, mark_price)
            except Exception as e:
                logger.warning(f"REST price polling failed: {e}")
        
        # Poll candles via REST for all symbols (since WS candles not working)
        for sym_config in self.config.symbols:
            symbol = sym_config.symbol
            for res in [sym_config.resolution] + ([sym_config.htf_resolution] if sym_config.htf_resolution else []):
                try:
                    end = int(time.time())
                    start = end - sym_config.lookback * 300  # 5m = 300s
                    candles = await self.engine.client.get_candles(symbol, res, start, end, limit=sym_config.lookback)
                    for c in candles:
                        candle_store.add_candle(symbol, res, Candle(
                            timestamp=c.timestamp,
                            open=c.open,
                            high=c.high,
                            low=c.low,
                            close=c.close,
                            volume=c.volume
                        ))
                except Exception as e:
                    logger.warning(f"REST candle polling failed for {symbol} {res}: {e}")
        
        # Process each symbol
        for sym_config in self.config.symbols:
            symbol = sym_config.symbol
            
            # Risk check
            pos_value = 0
            if symbol in self._positions:
                pos = self._positions[symbol]
                pos_value = pos.size * pos.entry_price * sym_config.contract_size
            
            pos_pct = pos_value / self._current_equity if self._current_equity > 0 else 0
            
            risk_check = self.risk_manager.check_risk_limits(
                current_equity=self._current_equity,
                peak_equity=self._peak_equity,
                daily_pnl=self._daily_pnl,
                consecutive_losses=self._consecutive_losses,
                symbol=symbol,
                position_size_pct=pos_pct
            )
            
            if risk_check.action == RiskAction.KILL_SWITCH:
                logger.error(f"KILL SWITCH: {risk_check.reason}")
                await self._close_all_positions("kill_switch")
                self._running = False
                break
            
            if risk_check.action == RiskAction.BLOCK:
                continue
            
            # Get data
            df = candle_store.get_df(symbol, sym_config.resolution, lookback=sym_config.lookback)
            if len(df) < sym_config.lookback:
                logger.debug(f"{symbol}: insufficient data ({len(df)} < {sym_config.lookback})")
                continue
            
            # Add indicators
            df = all_indicators(df, sym_config.model_dump())
            
            # HTF data
            htf_df = None
            if sym_config.htf_resolution:
                htf_df = candle_store.get_df(symbol, sym_config.htf_resolution, lookback=sym_config.lookback)
                if len(htf_df) > 0:
                    htf_df = all_indicators(htf_df, sym_config.model_dump())
            
            # Generate signal
            signal = self.signal_engine.generate_signal(symbol, sym_config.model_dump(), df, htf_df)
            logger.info(f"{symbol}: signal={'YES' if signal else 'NO'}" + (f" side={signal.side.value} conf={signal.confidence:.2f}" if signal else ""))
            
            if signal and symbol not in self._positions:
                # Check max concurrent
                if len(self._positions) < sym_config.max_concurrent:
                    await self._execute_signal(signal, sym_config)
            
            # Manage existing positions - pass current price from candle
            current_price = df['close'].iloc[-1] if len(df) > 0 else None
            # Lock acquired inside _manage_position (single choke point)
            await self._manage_position(symbol, sym_config, df, current_price)
        
        # Persist candles periodically
        candle_store.persist_all()
    
    async def _execute_signal(self, signal: Signal, sym_config):
        """Execute a trading signal"""
        config_dict = sym_config.model_dump()
        
        # Calculate position size
        size = self.adaptive_risk.calculate_position_size(
            equity=self._current_equity,
            entry_price=signal.price,
            stop_loss=signal.price - signal.atr * (1 + config_dict.get('sl_buffer_atr', 0.1)) if signal.side == SignalSide.LONG
                       else signal.price + signal.atr * (1 + config_dict.get('sl_buffer_atr', 0.1)),
            atr=signal.atr,
            regime=signal.regime,
            confidence=signal.confidence,
            symbol_config=config_dict
        )
        
        logger.info(f"EXECUTE {signal.symbol}: side={signal.side.value} size={size:.4f} min_contracts={config_dict.get('min_contracts', 1)} atr={signal.atr:.2f}")
        
        if size < config_dict.get('min_contracts', 1):
            logger.warning(f"SKIP {signal.symbol}: size {size:.4f} < min_contracts {config_dict.get('min_contracts', 1)}")
            return
        
        # Calculate SL/TP
        if signal.side == SignalSide.LONG:
            sl = signal.price - signal.atr * (1 + config_dict.get('sl_buffer_atr', 0.1))
            tp1 = signal.price + signal.atr * config_dict.get('rr1', 1.5)
            tp2 = signal.price + signal.atr * config_dict.get('rr2', 2.5)
        else:
            sl = signal.price + signal.atr * (1 + config_dict.get('sl_buffer_atr', 0.1))
            tp1 = signal.price - signal.atr * config_dict.get('rr1', 1.5)
            tp2 = signal.price - signal.atr * config_dict.get('rr2', 2.5)
        
        # Place order
        order = await self.engine.place_order(
            symbol=signal.symbol,
            side=signal.side.value,
            size=size,
            entry_price=signal.price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2
        )
        
        if order:
            pos = Position(
                symbol=signal.symbol,
                side=signal.side.value,
                size=size,
                entry_price=signal.price,
                entry_time=signal.timestamp,
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
                contract_size=config_dict.get('contract_size', 1.0),
                regime=signal.regime,
                confidence=signal.confidence,
                agents=signal.agents
            )
            self._positions[signal.symbol] = pos
            self.risk_manager.on_trade_open(config_dict.get('risk_per_trade', 0.02))
            
            logger.info(f"Opened {signal.side.value} {signal.symbol} size={size:.4f} @ {signal.price:.4f}")
    
    async def _manage_position(self, symbol: str, sym_config, df: pd.DataFrame, mark_price: float = None):
        """Manage open position - check exits, trail stops"""
        if symbol not in self._positions:
            return
        
        pos = self._positions[symbol]
        
        # Get current price: prefer mark_price from ticker, fallback to candle close
        if mark_price is not None:
            current_price = mark_price
            logger.info(f"Using ticker mark_price for {symbol}: {current_price}")
        elif df is not None and len(df) > 0:
            current_price = df['close'].iloc[-1]
            logger.info(f"Using candle close for {symbol}: {current_price}")
        else:
            current_price = pos.entry_price
            logger.warning(f"No price source for {symbol}, using entry: {current_price}")
        
        atr = df['atr'].iloc[-1] if df is not None and len(df) > 0 else 0
        
        # Check exits
        exits = self.engine.check_exits(symbol, current_price)
        logger.info(f"Exits for {symbol} @ {current_price}: {exits}")
        
        async with self._position_lock:
            # Re-check position exists inside lock
            if symbol not in self._positions:
                logger.info(f"Position {symbol} already closed, skipping")
                return
            pos = self._positions[symbol]
            
            for exit_reason in exits:
                if exit_reason == 'take_profit_1' and not pos.partial_filled:
                    pnl = self.engine.partial_close(symbol, current_price, 
                                                   sym_config.model_dump().get('partial_at_rr1', 0.5))
                    self._daily_pnl += pnl
                    if pnl < 0:
                        self._consecutive_losses += 1
                    else:
                        self._consecutive_losses = 0
                    pos.trail_price = pos.entry_price  # Move to breakeven
                    logger.info(f"TP1 hit for {symbol}, moved to breakeven")
                    # Save state after partial close
                    self._save_state()
                    return  # Exit after handling TP1 to avoid double-processing
                
                elif exit_reason in ('take_profit_2', 'stop_loss', 'trail'):
                    # Capture position before close
                    pos = self._positions.get(symbol)
                    if pos is None:
                        logger.warning(f"Position {symbol} already closed, skipping")
                        return
                    pnl = self.engine.close_position(symbol, current_price, exit_reason)
                    self._daily_pnl += pnl
                    if pnl < 0:
                        self._consecutive_losses += 1
                    else:
                        self._consecutive_losses = 0
                    self.risk_manager.on_trade_close(pnl)
                    self.adaptive_risk.record_trade({
                        'symbol': symbol,
                        'pnl': pnl,
                        'exit_reason': exit_reason,
                        'regime': pos.regime,
                        'confidence': pos.confidence
                    })
                    # Record to performance tracker
                    self.performance_tracker.record_trade(
                        TradeRecord(
                            symbol=symbol,
                            side=pos.side,
                            entry_price=pos.entry_price,
                            exit_price=current_price,
                            size=pos.size,
                            entry_time=pos.entry_time,
                            exit_time=int(time.time() * 1000),
                            pnl=pnl,
                            pnl_pct=pnl / (pos.entry_price * pos.size) if pos.size > 0 else 0,
                            regime=pos.regime,
                            confidence=pos.confidence
                        )
                    )
                    # Save state after full close
                    self._save_state()
        
        # Update trailing stop (only if we have df with ATR)
        if df is not None and len(df) > 0 and atr > 0:
            config_dict = sym_config.model_dump()
            if pos.side == 'long' and current_price > pos.entry_price:
                new_trail = current_price - atr * config_dict.get('trail_atr_mult', 1.5)
                if pos.trail_price is None or new_trail > pos.trail_price:
                    pos.trail_price = new_trail
            elif pos.side == 'short' and current_price < pos.entry_price:
                new_trail = current_price + atr * config_dict.get('trail_atr_mult', 1.5)
                if pos.trail_price is None or new_trail < pos.trail_price:
                    pos.trail_price = new_trail
    
    async def _close_all_positions(self, reason: str):
        """Emergency close all positions"""
        for symbol, pos in list(self._positions.items()):
            # Get current price from ticker
            try:
                tickers = await self.engine.client.get_tickers([symbol])
                if tickers:
                    price = tickers[0]['mark_price']
                    pnl = self.engine.close_position(symbol, price, reason)
                    # Record emergency close to performance tracker
                    self.performance_tracker.record_trade(
                        TradeRecord(
                            symbol=symbol,
                            side=pos.side,
                            entry_price=pos.entry_price,
                            exit_price=price,
                            size=pos.size,
                            entry_time=pos.entry_time,
                            exit_time=int(time.time() * 1000),
                            pnl=pnl,
                            pnl_pct=pnl / (pos.entry_price * pos.size) if pos.size > 0 else 0,
                            regime=pos.regime,
                            confidence=pos.confidence
                        )
                    )
            except Exception:
                self.engine.close_position(symbol, pos.entry_price, reason)
    
    def get_status(self) -> Dict:
        return {
            "state": "running" if self._running else "stopped",
            "uptime": time.time() - self._start_time,
            "equity": self._current_equity,
            "daily_pnl": self._daily_pnl,
            "drawdown": (self._peak_equity - self._current_equity) / self._peak_equity if self._peak_equity > 0 else 0,
            "positions": len(self._positions),
            "consecutive_losses": self._consecutive_losses,
            "last_heartbeat": self._heartbeat_time,
        }
    
    async def stop(self):
        self._running = False
        if self._main_task:
            self._main_task.cancel()
        if self._perf_task:
            self._perf_task.cancel()
        self.auto_optimizer.stop()
        await self.engine.stop()
        if self._ws_client:
            await self._ws_client.stop()
        if self._ticker_ws:
            await self._ticker_ws.stop()
        self._save_state()
        logger.info("AjayBot stopped")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    
    config = load_config("config/config.yaml")
    bot = AjayBot(config)
    await bot.start()


if __name__ == "__main__":
    from .config import load_config
    asyncio.run(main())