"""
Risk Management - Position sizing, drawdown control, Kelly criterion
"""
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class RiskAction(Enum):
    ALLOW = "allow"
    REDUCE = "reduce"
    BLOCK = "block"
    KILL_SWITCH = "kill_switch"


@dataclass
class RiskMetrics:
    current_equity: float
    peak_equity: float
    daily_pnl: float
    consecutive_losses: int
    drawdown_pct: float
    daily_loss_pct: float
    action: RiskAction
    reason: str


class RiskManager:
    """Comprehensive risk management"""
    
    def __init__(self, config):
        self.config = config.risk
        self.daily_start_equity = config.risk.paper_equity
        self.last_reset_date = None
        self.kill_switch = False
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        
    def reset_daily(self, current_equity: float):
        """Reset daily tracking"""
        self.daily_start_equity = current_equity
        self.daily_pnl = 0.0
        self.last_reset_date = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date()
    
    def check_risk_limits(self, current_equity: float, peak_equity: float, 
                          daily_pnl: float, consecutive_losses: int,
                          symbol: str = None, position_size_pct: float = 0) -> RiskMetrics:
        """Check all risk limits and return action"""
        
        drawdown_pct = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
        daily_loss_pct = -daily_pnl / self.daily_start_equity if self.daily_start_equity > 0 else 0
        
        self.consecutive_losses = consecutive_losses
        self.daily_pnl = daily_pnl
        
        # Kill switch - max drawdown
        if drawdown_pct >= self.config.max_dd_kill_pct:
            self.kill_switch = True
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.KILL_SWITCH,
                reason=f"Max drawdown exceeded: {drawdown_pct:.1%} >= {self.config.max_dd_kill_pct:.1%}"
            )
        
        # Daily loss limit
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.BLOCK,
                reason=f"Daily loss limit: {daily_loss_pct:.1%} >= {self.config.max_daily_loss_pct:.1%}"
            )
        
        # Consecutive losses pause
        if consecutive_losses >= self.config.consecutive_loss_pause:
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.BLOCK,
                reason=f"Consecutive losses: {consecutive_losses} >= {self.config.consecutive_loss_pause}"
            )
        
        # Position size limit
        if position_size_pct > self.config.max_position_pct:
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.REDUCE,
                reason=f"Position size {position_size_pct:.1%} > max {self.config.max_position_pct:.1%}"
            )
        
        # Warning zone - reduce risk
        if drawdown_pct >= self.config.max_dd_kill_pct * 0.7:
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.REDUCE,
                reason=f"Approaching max DD: {drawdown_pct:.1%}"
            )
        
        if daily_loss_pct >= self.config.max_daily_loss_pct * 0.7:
            return RiskMetrics(
                current_equity=current_equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                drawdown_pct=drawdown_pct,
                daily_loss_pct=daily_loss_pct,
                action=RiskAction.REDUCE,
                reason=f"Approaching daily loss limit: {daily_loss_pct:.1%}"
            )
        
        return RiskMetrics(
            current_equity=current_equity,
            peak_equity=peak_equity,
            daily_pnl=daily_pnl,
            consecutive_losses=consecutive_losses,
            drawdown_pct=drawdown_pct,
            daily_loss_pct=daily_loss_pct,
            action=RiskAction.ALLOW,
            reason="OK"
        )
    
    def on_trade_open(self, risk_per_trade: float):
        """Called when trade opens"""
        pass
    
    def on_trade_close(self, pnl: float):
        """Called when trade closes"""
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0


class AdaptiveRiskManager:
    """Adaptive position sizing using Kelly criterion and volatility scaling"""
    
    def __init__(self, config):
        self.config = config
        self.adaptive_config = config.adaptive if hasattr(config, 'adaptive') else None
        self.trade_history = []
        self.regime_multipliers = {
            'strong_trend': 1.5,
            'weak_trend': 1.2,
            'breakout': 1.5,
            'volatile_range': 0.7,
            'quiet_range': 1.0,
            'range': 1.0,
            'unknown': 1.0,
        }
        
    def calculate_position_size(self, equity: float, entry_price: float, stop_loss: float,
                                atr: float, regime: str, confidence: float,
                                symbol_config: Dict) -> float:
        """Calculate position size using adaptive Kelly + risk per trade"""
        
        # Base risk per trade from config
        base_risk = symbol_config.get('risk_per_trade', 0.02)
        
        # Risk distance
        risk_distance = abs(entry_price - stop_loss)
        if risk_distance <= 0:
            return 0
        
        # Regime multiplier
        regime_mult = self.regime_multipliers.get(regime, 1.0)
        
        # Confidence scaling
        conf_mult = confidence if self.adaptive_config and self.adaptive_config.confidence_scaling else 1.0
        
        # Volatility scaling
        vol_mult = 1.0
        if self.adaptive_config and self.adaptive_config.volatility_scaling and atr > 0:
            # Normalize ATR to price
            atr_pct = atr / entry_price
            target_atr_pct = 0.02  # 2% target volatility
            vol_mult = target_atr_pct / max(atr_pct, 0.005)
            vol_mult = np.clip(vol_mult, 0.5, 2.0)
        
        # Kelly fraction
        kelly_fraction = 0.25
        if self.adaptive_config:
            kelly_fraction = self.adaptive_config.kelly_fraction
        
        # Win rate estimation from recent trades
        win_rate = self._estimate_win_rate()
        if win_rate > 0:
            avg_win = self._estimate_avg_win()
            avg_loss = self._estimate_avg_loss()
            if avg_loss > 0:
                kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
                kelly = np.clip(kelly, 0, kelly_fraction)
            else:
                kelly = kelly_fraction
        else:
            kelly = kelly_fraction
        
        # Final risk per trade
        risk_per_trade = base_risk * regime_mult * conf_mult * vol_mult * kelly
        risk_per_trade = np.clip(risk_per_trade, 0.005, 0.05)  # 0.5% to 5%
        
        # Position size in quote currency
        risk_amount = equity * risk_per_trade
        
        # Convert to contracts
        contract_size = symbol_config.get('contract_size', 1)
        position_size = risk_amount / (risk_distance * contract_size)
        
        # Min contracts
        min_contracts = symbol_config.get('min_contracts', 1)
        if position_size < min_contracts:
            return 0
        
        # Max position size (max_position_pct of equity)
        max_pos_value = equity * self.config.risk.max_position_pct
        max_contracts = max_pos_value / (entry_price * contract_size)
        position_size = min(position_size, max_contracts)
        
        return max(0, position_size)
    
    def _estimate_win_rate(self) -> float:
        if len(self.trade_history) < 10:
            return 0.5
        recent = self.trade_history[-50:]
        wins = sum(1 for t in recent if t.get('pnl', 0) > 0)
        return wins / len(recent)
    
    def _estimate_avg_win(self) -> float:
        wins = [t['pnl'] for t in self.trade_history if t.get('pnl', 0) > 0]
        return np.mean(wins) if wins else 0
    
    def _estimate_avg_loss(self) -> float:
        losses = [abs(t['pnl']) for t in self.trade_history if t.get('pnl', 0) < 0]
        return np.mean(losses) if losses else 0
    
    def record_trade(self, trade: Dict):
        """Record closed trade for learning"""
        self.trade_history.append(trade)
        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-500:]