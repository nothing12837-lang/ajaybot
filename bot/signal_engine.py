"""
Signal Generation Engine - Multi-agent signal aggregation with AI Analyst
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone

import pandas as pd
import numpy as np

from .indicators import detect_regime
from .ai_analyst import AIAnalystAgent, MarketStructure, MarketRegime, create_ai_analyst

logger = logging.getLogger(__name__)


class SignalSide(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class Signal:
    symbol: str
    timestamp: int
    side: SignalSide
    confidence: float
    price: float
    atr: float
    agents: Dict[str, float]
    regime: str
    explanation: str = ""
    metadata: Dict = None


class BaseAgent:
    """Base class for signal agents"""
    name: str = "base"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        raise NotImplementedError


class MomentumAgent(BaseAgent):
    """Momentum-based signal using ADX + EMA alignment"""
    name = "momentum"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        if len(df) < 30:
            return 0.0
        
        last = df.iloc[-1]
        adx = last.get('adx', 0)
        plus_di = last.get('plus_di', 0)
        minus_di = last.get('minus_di', 0)
        ema_fast = last.get('ema_fast', 0)
        ema_slow = last.get('ema_slow', 0)
        ema_trend = last.get('ema_trend', 0)
        macd = last.get('macd', 0)
        macd_signal = last.get('macd_signal', 0)
        
        if pd.isna(adx) or adx < config.get('adx_trend_min', 15):
            return 0.0
        
        signal = 0.0
        # Strong trend alignment
        if plus_di > minus_di and ema_fast > ema_slow > ema_trend:
            signal = min(adx / 50.0, 1.0) * 0.7
            if macd > macd_signal:
                signal += 0.15
        elif minus_di > plus_di and ema_fast < ema_slow < ema_trend:
            signal = -min(adx / 50.0, 1.0) * 0.7
            if macd < macd_signal:
                signal -= 0.15
        
        return np.clip(signal, -1.0, 1.0)


class MeanReversionAgent(BaseAgent):
    """Mean reversion using Bollinger Bands + RSI"""
    name = "meanrev"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        if len(df) < 30:
            return 0.0
        
        last = df.iloc[-1]
        close = last.get('close', 0)
        bb_upper = last.get('bb_upper', 0)
        bb_lower = last.get('bb_lower', 0)
        bb_middle = last.get('bb_middle', 0)
        rsi = last.get('rsi', 50)
        stoch_k = last.get('stoch_rsi_k', 50)
        bb_width = last.get('bb_width', 0)
        
        if pd.isna(close) or bb_width > 0.1:  # Not in range
            return 0.0
        
        signal = 0.0
        # Oversold at lower band
        if close <= bb_lower and rsi < 35 and stoch_k < 20:
            signal = 0.6
        # Overbought at upper band
        elif close >= bb_upper and rsi > 65 and stoch_k > 80:
            signal = -0.6
        # Mild mean reversion
        elif close < bb_middle and rsi < 45:
            signal = 0.2
        elif close > bb_middle and rsi > 55:
            signal = -0.2
        
        return np.clip(signal, -1.0, 1.0)


class TrendAgent(BaseAgent):
    """Trend following using SuperTrend + EMA"""
    name = "trend"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        if len(df) < 50:
            return 0.0
        
        last = df.iloc[-1]
        st_trend = last.get('st_trend', 0)
        close = last.get('close', 0)
        supertrend = last.get('supertrend', 0)
        ema_fast = last.get('ema_fast', 0)
        ema_slow = last.get('ema_slow', 0)
        ema_200 = last.get('ema_200', 0)
        
        signal = 0.0
        if st_trend == 1 and close > supertrend:
            signal = 0.5
            if ema_fast > ema_slow > ema_200:
                signal = 0.8
        elif st_trend == -1 and close < supertrend:
            signal = -0.5
            if ema_fast < ema_slow < ema_200:
                signal = -0.8
        
        return np.clip(signal, -1.0, 1.0)


class BreakoutAgent(BaseAgent):
    """Breakout detection using volume + price action"""
    name = "breakout"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        if len(df) < 30:
            return 0.0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = last.get('close', 0)
        high = last.get('high', 0)
        low = last.get('low', 0)
        volume = last.get('volume', 0)
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        bb_width = last.get('bb_width', 0)
        atr = last.get('atr', 0)
        
        # Squeeze detection
        squeezed = bb_width < 0.03
        vol_spike = volume > avg_volume * 2 if avg_volume > 0 else False
        
        signal = 0.0
        if squeezed and vol_spike:
            # Direction from candle
            body = close - last.get('open', close)
            if body > atr * 0.5:
                signal = 0.7
            elif body < -atr * 0.5:
                signal = -0.7
        
        return np.clip(signal, -1.0, 1.0)


class OrderFlowAgent(BaseAgent):
    """Order flow / volume profile signals"""
    name = "order_flow"
    
    def compute(self, df: pd.DataFrame, config: Dict) -> float:
        if len(df) < 20:
            return 0.0
        
        last = df.iloc[-1]
        body_ratio = last.get('body_ratio', 0)
        upper_wick = last.get('upper_wick', 0)
        lower_wick = last.get('lower_wick', 0)
        close = last.get('close', 0)
        open_ = last.get('open', close)
        atr = last.get('atr', 0)
        
        signal = 0.0
        # Strong body with small wicks = conviction
        if body_ratio > 0.7:
            if close > open_:
                signal = 0.4
            else:
                signal = -0.4
        
        # Rejection wicks
        if upper_wick > lower_wick * 2 and upper_wick > atr * 0.5:
            signal -= 0.3
        elif lower_wick > upper_wick * 2 and lower_wick > atr * 0.5:
            signal += 0.3
        
        return np.clip(signal, -1.0, 1.0)


class SignalEngine:
    """Main signal generation engine with AI Analyst"""
    
    def __init__(self, config):
        self.config = config
        self.agents = {
            'momentum': MomentumAgent(),
            'meanrev': MeanReversionAgent(),
            'trend': TrendAgent(),
            'breakout': BreakoutAgent(),
            'order_flow': OrderFlowAgent(),
        }
        # AI Analyst agent
        self.ai_analyst = create_ai_analyst(config.model_dump() if hasattr(config, 'model_dump') else config)
        self.ai_weight = config.get('ai_analyst', {}).get('weight', 0.25) if isinstance(config, dict) else 0.25
        
        self.signal_history: List[Signal] = []
    
    def _build_market_structure(self, symbol: str, df: pd.DataFrame, htf_df: pd.DataFrame = None) -> MarketStructure:
        """Build market structure from dataframes"""
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        
        # HTF structure
        htf_trend = "sideways"
        htf_structure = "ranging"
        if htf_df is not None and len(htf_df) > 30:
            htf_last = htf_df.iloc[-1]
            htf_ema_fast = htf_last.get('ema_fast', 0)
            htf_ema_slow = htf_last.get('ema_slow', 0)
            htf_ema_trend = htf_last.get('ema_trend', 0)
            if htf_ema_fast > htf_ema_slow > htf_ema_trend:
                htf_trend = "up"
                htf_structure = "HH/HL"
            elif htf_ema_fast < htf_ema_slow < htf_ema_trend:
                htf_trend = "down"
                htf_structure = "LH/LL"
        
        # LTF structure
        ema_fast = last.get('ema_fast', 0)
        ema_slow = last.get('ema_slow', 0)
        ema_trend = last.get('ema_trend', 0)
        ltf_structure = "ranging"
        if ema_fast > ema_slow > ema_trend:
            ltf_structure = "HH/HL"
        elif ema_fast < ema_slow < ema_trend:
            ltf_structure = "LH/LL"
        
        # Key levels
        support = last.get('bb_lower', 0)
        resistance = last.get('bb_upper', 0)
        pivot = last.get('bb_middle', 0)
        
        # Order flow bias from recent candles
        recent = df.tail(20)
        up_volume = recent[recent['close'] > recent['open']]['volume'].sum()
        down_volume = recent[recent['close'] < recent['open']]['volume'].sum()
        total_vol = up_volume + down_volume
        order_flow_bias = (up_volume - down_volume) / total_vol if total_vol > 0 else 0
        
        # Liquidity zones (recent highs/lows)
        highs = recent['high'].nlargest(3).tolist()
        lows = recent['low'].nsmallest(3).tolist()
        liquidity_zones = highs + lows
        
        return MarketStructure(
            symbol=symbol,
            htf_trend=htf_trend,
            htf_structure=htf_structure,
            ltf_structure=ltf_structure,
            key_levels={'support': support, 'resistance': resistance, 'pivot': pivot},
            volume_profile={'up_vol': up_volume, 'down_vol': down_volume},
            order_flow_bias=order_flow_bias,
            liquidity_zones=liquidity_zones
        )
    
    def _determine_regime(self, df: pd.DataFrame) -> MarketRegime:
        """Determine market regime"""
        regime_str = detect_regime(df)
        if 'strong_trend' in regime_str:
            if 'up' in regime_str or df.iloc[-1].get('ema_fast', 0) > df.iloc[-1].get('ema_slow', 0):
                return MarketRegime.STRONG_TREND_UP
            return MarketRegime.STRONG_TREND_DOWN
        elif 'weak_trend' in regime_str:
            if df.iloc[-1].get('ema_fast', 0) > df.iloc[-1].get('ema_slow', 0):
                return MarketRegime.WEAK_TREND_UP
            return MarketRegime.WEAK_TREND_DOWN
        elif 'choppy' in regime_str:
            return MarketRegime.CHOPPY
        elif 'high_vol' in regime_str:
            return MarketRegime.HIGH_VOLATILITY
        return MarketRegime.RANGING
    
    def generate_signal(self, symbol: str, sym_config: Dict, df: pd.DataFrame, htf_df: pd.DataFrame = None) -> Optional[Signal]:
        """Generate aggregated signal for a symbol with AI Analyst integration"""
        latest = df.iloc[-1]
        atr = latest.get('atr', 0)
        price = latest.get('close', 0)
        
        if pd.isna(atr) or atr <= 0 or pd.isna(price):
            return None
        
        # Run all quantitative agents
        agent_signals = {}
        for name, agent in self.agents.items():
            try:
                agent_signals[name] = agent.compute(df, sym_config)
            except Exception as e:
                logger.warning(f"Agent {name} error: {e}")
                agent_signals[name] = 0.0
        
        # HTF confirmation
        htf_bias = 0.0
        if htf_df is not None and len(htf_df) > 30:
            htf_last = htf_df.iloc[-1]
            htf_ema_fast = htf_last.get('ema_fast', 0)
            htf_ema_slow = htf_last.get('ema_slow', 0)
            htf_ema_trend = htf_last.get('ema_trend', 0)
            if htf_ema_fast > htf_ema_slow > htf_ema_trend:
                htf_bias = 0.2
            elif htf_ema_fast < htf_ema_slow < htf_ema_trend:
                htf_bias = -0.2
        
        # Build market structure for AI Analyst
        market_structure = self._build_market_structure(symbol, df, htf_df)
        regime = self._determine_regime(df)
        
        # Get additional market data for AI Analyst
        volume_24h = df['volume'].tail(288).sum() * price  # Approximate 24h volume
        funding_rate = 0.0  # Would come from ticker
        open_interest = 0.0  # Would come from ticker
        fear_greed = None
        news_sentiment = None
        btc_correlation = None
        
        # Weighted aggregation of quant agents
        weights = {
            'momentum': 0.30,
            'trend': 0.25,
            'meanrev': 0.15,
            'breakout': 0.15,
            'order_flow': 0.15,
        }
        
        quant_signal = sum(agent_signals[k] * weights.get(k, 0.1) for k in agent_signals)
        quant_signal += htf_bias * 0.2
        
        # AI Analyst decision (async, so we run it in background)
        ai_decision = None
        try:
            # Check if we have event loop running
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create task for AI analyst
                asyncio.create_task(self._get_ai_decision(
                    symbol, agent_signals, market_structure, regime,
                    price, atr, volume_24h, funding_rate, open_interest,
                    fear_greed, news_sentiment, btc_correlation, htf_bias
                ))
        except Exception:
            pass
        
        # For now, use quant signal with AI weight placeholder
        # The AI decision will be integrated in next cycle via signal adjustment
        net_signal = quant_signal * (1 - self.ai_weight)
        
        # Minimum confidence threshold
        min_conf = sym_config.get('min_confidence', 0.15)
        if abs(net_signal) < min_conf:
            return None
        
        # Minimum agreeing agents
        agreeing = sum(1 for v in agent_signals.values() if abs(v) > 0.1)
        min_agree = sym_config.get('min_agents_agree', 1)
        if agreeing < min_agree:
            return None
        
        side = SignalSide.LONG if net_signal > 0 else SignalSide.SHORT
        confidence = min(abs(net_signal), 1.0)
        
        # Build explanation
        active_agents = [k for k, v in agent_signals.items() if abs(v) > 0.15]
        explanation = f"Agents: {', '.join(active_agents)} | Regime: {regime.value} | HTF bias: {htf_bias:.2f}"
        
        signal = Signal(
            symbol=symbol,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            side=side,
            confidence=confidence,
            price=price,
            atr=atr,
            agents=agent_signals,
            regime=regime.value,
            explanation=explanation,
            metadata={'htf_bias': htf_bias, 'agreeing': agreeing, 'quant_signal': quant_signal}
        )
        
        self.signal_history.append(signal)
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-500:]
        
        return signal
    
    async def _get_ai_decision(
        self,
        symbol: str,
        quant_signals: Dict[str, float],
        market_structure: MarketStructure,
        regime: MarketRegime,
        price: float,
        atr: float,
        volume_24h: float,
        funding_rate: float,
        open_interest: float,
        fear_greed: Optional[int],
        news_sentiment: Optional[float],
        btc_correlation: Optional[float],
        htf_bias: float
    ):
        """Get AI Analyst decision asynchronously"""
        try:
            decision = await self.ai_analyst.analyze(
                symbol, quant_signals, market_structure, regime,
                price, atr, volume_24h, funding_rate, open_interest,
                fear_greed, news_sentiment, btc_correlation, htf_bias
            )
            if decision:
                # Store for next cycle integration
                self._last_ai_decision = decision
        except Exception as e:
            logger.warning(f"AI Analyst async error: {e}")