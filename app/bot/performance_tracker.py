"""
Performance Tracker for AjayBot
Tracks accuracy, returns, and alerts when thresholds are met.
"""

import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import statistics


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    entry_time: int
    exit_time: int
    pnl: float
    pnl_pct: float
    regime: str
    confidence: float


class PerformanceTracker:
    def __init__(self, state_file: str = "data/bot_state.json", 
                 trades_file: str = "data/trades_history.json",
                 config: dict = None):
        self.state_file = Path(state_file)
        self.trades_file = Path(trades_file)
        self.config = config or {}
        self.accuracy_threshold = self.config.get('accuracy_threshold', 0.80)  # 80%
        self.monthly_return_threshold = self.config.get('monthly_return_threshold', 0.10)  # 10%
        self.trades: List[TradeRecord] = []
        self._load_trades()
        self._alerted = False
        
    def _load_trades(self):
        if self.trades_file.exists():
            try:
                with open(self.trades_file) as f:
                    data = json.load(f)
                    self.trades = [TradeRecord(**t) for t in data]
            except Exception:
                self.trades = []
    
    def _save_trades(self):
        self.trades_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trades_file, 'w') as f:
            json.dump([asdict(t) for t in self.trades], f, indent=2)
    
    def record_trade(self, trade: TradeRecord):
        self.trades.append(trade)
        self._save_trades()
        self._check_thresholds()
    
    def get_accuracy(self, lookback: int = 100) -> float:
        """Calculate win rate over recent trades"""
        if not self.trades:
            return 0.0
        recent = self.trades[-lookback:]
        wins = sum(1 for t in recent if t.pnl > 0)
        return wins / len(recent)
    
    def get_monthly_return(self) -> float:
        """Calculate return over last 30 days"""
        if not self.trades:
            return 0.0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
        recent = [t for t in self.trades if t.exit_time / 1000 > cutoff]
        if not recent:
            return 0.0
        total_pnl = sum(t.pnl for t in recent)
        # Estimate capital from equity (rough)
        return total_pnl / 1000.0  # paper equity baseline
    
    def get_total_trades(self) -> int:
        return len(self.trades)
    
    def get_win_loss_stats(self) -> dict:
        if not self.trades:
            return {"wins": 0, "losses": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0}
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        return {
            "wins": len(wins),
            "losses": len(losses),
            "avg_win": statistics.mean(wins) if wins else 0,
            "avg_loss": statistics.mean(losses) if losses else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses else float('inf'),
            "net_pnl": sum(wins) + sum(losses),
        }
    
    def _check_thresholds(self):
        if self._alerted:
            return
        accuracy = self.get_accuracy()
        monthly_return = self.get_monthly_return()
        
        if accuracy >= self.accuracy_threshold and monthly_return >= self.monthly_return_threshold:
            self._alerted = True
            self._send_alert(accuracy, monthly_return)
    
    def _send_alert(self, accuracy: float, monthly_return: float):
        """Alert when thresholds met - prints to console, can extend to Telegram"""
        msg = (
            f"\n{'='*60}\n"
            f"🎯 PERFORMANCE THRESHOLDS MET!\n"
            f"{'='*60}\n"
            f"Accuracy: {accuracy:.1%} (target: {self.accuracy_threshold:.0%})\n"
            f"Monthly Return: {monthly_return:.1%} (target: {self.monthly_return_threshold:.0%})\n"
            f"Total Trades: {self.get_total_trades()}\n"
            f"Stats: {self.get_win_loss_stats()}\n"
            f"{'='*60}\n"
            f"✅ Ready for live API keys!\n"
            f"{'='*60}\n"
        )
        print(msg)
        # Log to file
        alert_file = Path("data/threshold_alert.log")
        alert_file.parent.mkdir(parents=True, exist_ok=True)
        with open(alert_file, 'a') as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} - {msg}\n")
    
    def get_summary(self) -> dict:
        return {
            "total_trades": self.get_total_trades(),
            "accuracy": self.get_accuracy(),
            "monthly_return": self.get_monthly_return(),
            "accuracy_threshold": self.accuracy_threshold,
            "monthly_return_threshold": self.monthly_return_threshold,
            "thresholds_met": self._alerted,
            "stats": self.get_win_loss_stats(),
        }


async def track_performance_loop(tracker: PerformanceTracker, interval: int = 300):
    """Background task to periodically report performance"""
    while True:
        await asyncio.sleep(interval)
        summary = tracker.get_summary()
        print(f"\n📊 Performance: Trades={summary['total_trades']}, "
              f"Accuracy={summary['accuracy']:.1%}, "
              f"Monthly Return={summary['monthly_return']:.1%}, "
              f"Net PnL={summary['stats']['net_pnl']:.2f}")


# Integration helper for bot.py
def create_performance_tracker(config: dict = None) -> PerformanceTracker:
    return PerformanceTracker(config=config)