"""
Strategy Adaptation Engine for AjayBot
========================================
Monitors per-symbol win rates in real-time windows. When an edge deteriorates:
  1. Raises confidence threshold to reduce frequency on weak symbols
  2. Rotates capital toward strongest performing symbols
  3. Sends Telegram alert with full diagnosis + new strategy
  4. Logs every adaptation decision to data/adaptation_log.json

This is the "grok-agent-style" autonomous adaptation loop:
  "When one strategy stopped working, the AI changed its approach
   and continued operating."
"""
from __future__ import annotations

import json
import asyncio
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import deque

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────
# Thresholds — tunable via config
# ──────────────────────────────────────────────────
DEFAULT_WINDOW_TRADES = 20          # evaluate every N trades per symbol
DEFAULT_MIN_TRADES = 5              # skip evaluation if fewer trades
DEFAULT_WARN_WIN_RATE = 0.40        # below this → warn, tighten confidence
DEFAULT_KILL_WIN_RATE = 0.30        # below this → pause symbol entirely
DEFAULT_COOL_WIN_RATE = 0.50        # above this → re-activate paused symbol
DEFAULT_CONF_BOOST = 0.05           # raise min_confidence by this on warning
DEFAULT_CONF_MAX = 0.35             # ceiling for auto-tightened confidence
DEFAULT_COOLDOWN_SECONDS = 3600     # min time between adaptations per symbol
DEFAULT_GLOBAL_EVAL_INTERVAL = 300  # run global evaluation every 5 minutes


# ──────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────
@dataclass
class AdaptationEvent:
    timestamp: float
    symbol: str
    action: str          # "warn" | "pause" | "resume" | "global_rotate"
    trigger: str         # human-readable why
    old_conf: float
    new_conf: float
    win_rate: float
    total_trades: int
    adaptation_count: int


@dataclass
class SymbolStats:
    symbol: str
    recent_trades: deque = field(default_factory=lambda: deque(maxlen=20))
    is_paused: bool = False
    current_conf_threshold: float = 0.15
    last_adaptation_ts: float = 0.0
    adaptation_count: int = 0
    total_trades: int = 0
    total_pnl: float = 0.0
    streak: int = 0                  # +N for wins, -N for losses

    def record_trade(self, pnl: float):
        self.total_trades += 1
        self.total_pnl += pnl
        win = pnl > 0
        self.recent_trades.append(win)
        if win:
            self.streak = max(0, self.streak) + 1
        else:
            self.streak = min(0, self.streak) - 1

    @property
    def win_rate(self) -> float:
        if not self.recent_trades:
            return 0.5
        return sum(self.recent_trades) / len(self.recent_trades)

    @property
    def sample_size(self) -> int:
        return len(self.recent_trades)


# ──────────────────────────────────────────────────
# Main engine
# ──────────────────────────────────────────────────
class StrategyAdaptationEngine:
    """
    Drop-in component for AjayBot.
    Plug into trade close events via `on_trade_closed()`.
    Run `start()` to launch the background evaluation loop.
    """

    def __init__(
        self,
        symbols: List[str],
        base_conf_thresholds: Optional[Dict[str, float]] = None,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        data_dir: str = "data",
        warn_win_rate: float = DEFAULT_WARN_WIN_RATE,
        kill_win_rate: float = DEFAULT_KILL_WIN_RATE,
        cool_win_rate: float = DEFAULT_COOL_WIN_RATE,
        conf_boost: float = DEFAULT_CONF_BOOST,
        conf_max: float = DEFAULT_CONF_MAX,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        eval_interval: float = DEFAULT_GLOBAL_EVAL_INTERVAL,
    ):
        self.symbols = symbols
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.data_dir / "adaptation_log.json"

        self.warn_win_rate = warn_win_rate
        self.kill_win_rate = kill_win_rate
        self.cool_win_rate = cool_win_rate
        self.conf_boost = conf_boost
        self.conf_max = conf_max
        self.cooldown_seconds = cooldown_seconds
        self.eval_interval = eval_interval

        # Per-symbol state
        base = base_conf_thresholds or {}
        self.stats: Dict[str, SymbolStats] = {
            s: SymbolStats(symbol=s, current_conf_threshold=base.get(s, 0.15))
            for s in symbols
        }

        # Adaptation history
        self.history: List[AdaptationEvent] = []
        self._load_log()

        # Background loop
        self._task: Optional[asyncio.Task] = None
        self._running = False

        logger.info(
            f"StrategyAdaptationEngine initialized for {len(symbols)} symbols"
        )

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────
    def on_trade_closed(self, symbol: str, pnl: float):
        """Call this every time a position closes."""
        if symbol not in self.stats:
            self.stats[symbol] = SymbolStats(symbol=symbol)
        self.stats[symbol].record_trade(pnl)
        logger.debug(
            f"Adaptation: {symbol} trade recorded pnl={pnl:.2f} "
            f"win_rate={self.stats[symbol].win_rate:.2%}"
        )
        # Immediate check after each trade
        asyncio.create_task(self._evaluate_symbol(symbol))

    def get_conf_threshold(self, symbol: str) -> float:
        """AjayBot uses this to decide whether to act on a signal."""
        return self.stats.get(symbol, SymbolStats(symbol=symbol)).current_conf_threshold

    def is_symbol_paused(self, symbol: str) -> bool:
        """Returns True if adaptation engine has paused this symbol."""
        return self.stats.get(symbol, SymbolStats(symbol=symbol)).is_paused

    def get_dashboard(self) -> Dict[str, Any]:
        """Returns a snapshot of all symbol stats for status display."""
        return {
            sym: {
                "win_rate": f"{st.win_rate:.1%}",
                "sample_size": st.sample_size,
                "is_paused": st.is_paused,
                "conf_threshold": st.current_conf_threshold,
                "streak": st.streak,
                "total_trades": st.total_trades,
                "total_pnl": round(st.total_pnl, 2),
                "adaptation_count": st.adaptation_count,
            }
            for sym, st in self.stats.items()
        }

    def start(self):
        """Launch background evaluation loop."""
        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
        logger.info("StrategyAdaptationEngine started")

    def stop(self):
        """Stop background loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("StrategyAdaptationEngine stopped")

    # ──────────────────────────────────────────────
    # Evaluation logic
    # ──────────────────────────────────────────────
    async def _evaluation_loop(self):
        """Periodic global evaluation — runs every eval_interval seconds."""
        while self._running:
            await asyncio.sleep(self.eval_interval)
            await self._evaluate_all()

    async def _evaluate_all(self):
        """Evaluate all symbols and look for rotation opportunities."""
        best_symbol = None
        best_wr = 0.0
        worst_symbol = None
        worst_wr = 1.0

        for symbol in self.symbols:
            st = self.stats.get(symbol)
            if not st or st.sample_size < DEFAULT_MIN_TRADES:
                continue

            wr = st.win_rate
            if wr > best_wr:
                best_wr = wr
                best_symbol = symbol
            if wr < worst_wr:
                worst_wr = wr
                worst_symbol = symbol

            await self._evaluate_symbol(symbol)

        # Global rotation alert if spread is huge
        if best_symbol and worst_symbol and best_symbol != worst_symbol:
            spread = best_wr - worst_wr
            if spread > 0.25 and self.stats[worst_symbol].sample_size >= DEFAULT_MIN_TRADES:
                await self._send_rotation_alert(
                    best_symbol, best_wr, worst_symbol, worst_wr
                )

    async def _evaluate_symbol(self, symbol: str):
        """Evaluate a single symbol and take action if needed."""
        st = self.stats.get(symbol)
        if not st or st.sample_size < DEFAULT_MIN_TRADES:
            return

        now = time.time()
        wr = st.win_rate

        # Cooldown check
        if now - st.last_adaptation_ts < self.cooldown_seconds:
            return

        # ── PAUSE: below kill threshold ──────────────
        if wr < self.kill_win_rate and not st.is_paused:
            old_conf = st.current_conf_threshold
            st.is_paused = True
            st.last_adaptation_ts = now
            st.adaptation_count += 1
            event = AdaptationEvent(
                timestamp=now, symbol=symbol,
                action="pause",
                trigger=f"Win rate {wr:.1%} < kill threshold {self.kill_win_rate:.1%}",
                old_conf=old_conf,
                new_conf=st.current_conf_threshold,
                win_rate=wr,
                total_trades=st.total_trades,
                adaptation_count=st.adaptation_count,
            )
            self._record_event(event)
            await self._notify_telegram(self._format_pause_message(event))
            logger.warning(f"ADAPT: PAUSED {symbol} — win rate {wr:.1%}")

        # ── WARN: below warn threshold ────────────────
        elif wr < self.warn_win_rate and not st.is_paused:
            old_conf = st.current_conf_threshold
            new_conf = min(old_conf + self.conf_boost, self.conf_max)
            if new_conf != old_conf:
                st.current_conf_threshold = new_conf
                st.last_adaptation_ts = now
                st.adaptation_count += 1
                event = AdaptationEvent(
                    timestamp=now, symbol=symbol,
                    action="warn",
                    trigger=f"Win rate {wr:.1%} < warn threshold {self.warn_win_rate:.1%}",
                    old_conf=old_conf,
                    new_conf=new_conf,
                    win_rate=wr,
                    total_trades=st.total_trades,
                    adaptation_count=st.adaptation_count,
                )
                self._record_event(event)
                await self._notify_telegram(self._format_warn_message(event))
                logger.warning(
                    f"ADAPT: WARN {symbol} — conf raised {old_conf:.2f} → {new_conf:.2f}"
                )

        # ── RESUME: paused symbol recovered ───────────
        elif wr >= self.cool_win_rate and st.is_paused:
            old_conf = st.current_conf_threshold
            # Restore baseline confidence on recovery
            recovery_conf = max(0.15, old_conf - self.conf_boost * 2)
            st.current_conf_threshold = recovery_conf
            st.is_paused = False
            st.last_adaptation_ts = now
            st.adaptation_count += 1
            event = AdaptationEvent(
                timestamp=now, symbol=symbol,
                action="resume",
                trigger=f"Win rate {wr:.1%} recovered above {self.cool_win_rate:.1%}",
                old_conf=old_conf,
                new_conf=recovery_conf,
                win_rate=wr,
                total_trades=st.total_trades,
                adaptation_count=st.adaptation_count,
            )
            self._record_event(event)
            await self._notify_telegram(self._format_resume_message(event))
            logger.info(f"ADAPT: RESUMED {symbol} — win rate recovered to {wr:.1%}")

    # ──────────────────────────────────────────────
    # Telegram messages
    # ──────────────────────────────────────────────
    def _format_pause_message(self, e: AdaptationEvent) -> str:
        return (
            f"🔴 <b>AjayBot — Symbol PAUSED</b>\n\n"
            f"📊 <b>Symbol:</b> {e.symbol}\n"
            f"📉 <b>Win Rate:</b> {e.win_rate:.1%} (threshold: {self.kill_win_rate:.0%})\n"
            f"🔢 <b>Sample Trades:</b> {self.stats[e.symbol].sample_size}\n"
            f"❌ <b>Action:</b> Trading PAUSED — edge has broken down\n\n"
            f"🤖 <b>Adaptation #{e.adaptation_count}</b>\n"
            f"<i>Bot will auto-resume when win rate recovers above {self.cool_win_rate:.0%}</i>\n\n"
            f"🔄 <i>Auto-adapting. Continuing.</i>"
        )

    def _format_warn_message(self, e: AdaptationEvent) -> str:
        return (
            f"⚠️ <b>AjayBot — Strategy Adapted</b>\n\n"
            f"📊 <b>Symbol:</b> {e.symbol}\n"
            f"📉 <b>Win Rate:</b> {e.win_rate:.1%} (warn threshold: {self.warn_win_rate:.0%})\n"
            f"🎯 <b>Confidence Threshold:</b> {e.old_conf:.2f} → <b>{e.new_conf:.2f}</b>\n"
            f"💡 <b>Effect:</b> Only higher-quality signals will be executed\n\n"
            f"🤖 <b>Adaptation #{e.adaptation_count}</b>\n"
            f"<i>Edge is weakening. Tightening entry filter — quality over quantity.</i>"
        )

    def _format_resume_message(self, e: AdaptationEvent) -> str:
        return (
            f"✅ <b>AjayBot — Symbol RESUMED</b>\n\n"
            f"📊 <b>Symbol:</b> {e.symbol}\n"
            f"📈 <b>Win Rate:</b> {e.win_rate:.1%} (recovered!)\n"
            f"🎯 <b>Confidence Threshold:</b> {e.old_conf:.2f} → <b>{e.new_conf:.2f}</b> (relaxed)\n\n"
            f"🤖 <b>Adaptation #{e.adaptation_count}</b>\n"
            f"<i>Edge restored. Resuming full trading on {e.symbol}.</i>"
        )

    async def _send_rotation_alert(
        self, best: str, best_wr: float, worst: str, worst_wr: float
    ):
        """Alert when one symbol massively outperforms another."""
        msg = (
            f"🔄 <b>AjayBot — Capital Rotation Opportunity</b>\n\n"
            f"🏆 <b>Top Performer:</b> {best} (win rate: {best_wr:.1%})\n"
            f"💀 <b>Weakest Symbol:</b> {worst} (win rate: {worst_wr:.1%})\n"
            f"📊 <b>Gap:</b> {(best_wr - worst_wr):.1%}\n\n"
            f"💡 Consider focusing more capital on {best} until {worst} recovers.\n"
            f"<i>Bot automatically raised confidence threshold on {worst}.</i>"
        )
        await self._notify_telegram(msg)

    async def _notify_telegram(self, message: str):
        """Send message to Telegram."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug("Telegram not configured for adaptation engine")
            return
        try:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = urllib.parse.urlencode({
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload)
            import urllib.request as ur
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: ur.urlopen(req, timeout=10))
            logger.info("Adaptation alert sent to Telegram")
        except Exception as e:
            logger.error(f"Failed to send adaptation Telegram alert: {e}")

    # ──────────────────────────────────────────────
    # Log persistence
    # ──────────────────────────────────────────────
    def _record_event(self, event: AdaptationEvent):
        self.history.append(event)
        self._save_log()

    def _save_log(self):
        try:
            data = [asdict(e) for e in self.history[-500:]]  # keep last 500
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save adaptation log: {e}")

    def _load_log(self):
        try:
            if self.log_file.exists():
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.history = [AdaptationEvent(**d) for d in data]
                logger.info(f"Loaded {len(self.history)} past adaptation events")
        except Exception as e:
            logger.warning(f"Could not load adaptation log: {e}")
            self.history = []


# ──────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────
def create_adaptation_engine(config) -> StrategyAdaptationEngine:
    """Create an adaptation engine from AjayBot config object."""
    symbols = [s.symbol for s in config.symbols]
    base_conf = {s.symbol: s.min_confidence for s in config.symbols}
    return StrategyAdaptationEngine(
        symbols=symbols,
        base_conf_thresholds=base_conf,
        telegram_token=config.telegram.bot_token,
        telegram_chat_id=config.telegram.chat_id,
        data_dir=config.data_dir,
    )
