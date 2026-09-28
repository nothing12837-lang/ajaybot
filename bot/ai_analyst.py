"""
AI Analyst Agent - Human-like discretionary trading decisions using LLM
Enhanced version of KronosBot's AI Analyst with better prompting and multi-factor analysis
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    STRONG_TREND_UP = "strong_trend_up"
    STRONG_TREND_DOWN = "strong_trend_down"
    WEAK_TREND_UP = "weak_trend_up"
    WEAK_TREND_DOWN = "weak_trend_down"
    RANGING = "ranging"
    CHOPPY = "choppy"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT_PENDING = "breakout_pending"
    REVERSAL = "reversal"


@dataclass
class MarketStructure:
    """Multi-timeframe market structure analysis"""
    symbol: str
    htf_trend: str  # up, down, sideways
    htf_structure: str  # HH/HL, LH/LL, ranging
    ltf_structure: str
    key_levels: Dict[str, float]  # support, resistance, pivot
    volume_profile: Dict[str, Any]
    order_flow_bias: float  # -1 to 1
    liquidity_zones: List[float]


@dataclass
class AnalystDecision:
    """AI Analyst final decision"""
    symbol: str
    direction: str  # long, short, neutral
    confidence: float  # 0-1
    position_size_pct: float  # 0-1 of max size
    entry_zone: tuple  # (low, high)
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    reasoning: str
    key_factors: List[str]
    risk_factors: List[str]
    regime: MarketRegime
    timeframe_alignment: bool


class AIAnalystAgent:
    """
    Enhanced AI Analyst using LLM for discretionary decisions.
    Combines quantitative signals with qualitative market structure analysis.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.enabled = config.get('ai_analyst', {}).get('enabled', True)
        self.model = config.get('ai_analyst', {}).get('model', 'gemini-1.5-flash')
        self.weight = config.get('ai_analyst', {}).get('weight', 0.25)  # 25% weight in ensemble
        self.min_confidence = config.get('ai_analyst', {}).get('min_confidence', 0.6)
        
        # API key from config
        self.api_key = config.get('gemini_api_key', '')
        self.client = None
        self._init_client()
        
        # Cache for decisions
        self._decision_cache: Dict[str, AnalystDecision] = {}
        self._cache_ttl = 300  # 5 minutes
    
    def _init_client(self):
        """Initialize Gemini client"""
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model)
                logger.info(f"AI Analyst initialized with {self.model}")
            except Exception as e:
                logger.warning(f"Failed to init Gemini client: {e}")
                self.client = None
    
    async def analyze(
        self,
        symbol: str,
        quant_signals: Dict[str, float],  # agent_name -> signal (-1 to 1)
        market_structure: MarketStructure,
        regime: MarketRegime,
        current_price: float,
        atr: float,
        volume_24h: float,
        funding_rate: float,
        open_interest: float,
        fear_greed: Optional[int] = None,
        news_sentiment: Optional[float] = None,
        btc_correlation: Optional[float] = None,
        htf_bias: float = 0.0
    ) -> Optional[AnalystDecision]:
        """Get AI Analyst decision for a symbol"""
        
        if not self.enabled or not self.client:
            return None
        
        # Check cache
        cache_key = f"{symbol}_{int(datetime.now().timestamp() / self._cache_ttl)}"
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        
        # Build comprehensive prompt
        prompt = self._build_prompt(
            symbol, quant_signals, market_structure, regime,
            current_price, atr, volume_24h, funding_rate,
            open_interest, fear_greed, news_sentiment,
            btc_correlation, htf_bias
        )
        
        try:
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config={
                    'temperature': 0.3,
                    'max_output_tokens': 2048,
                    'response_mime_type': 'application/json'
                }
            )
            
            decision = self._parse_response(response.text, symbol, current_price, atr, regime)
            
            if decision and decision.confidence >= self.min_confidence:
                self._decision_cache[cache_key] = decision
                logger.info(f"AI Analyst {symbol}: {decision.direction} "
                           f"conf={decision.confidence:.2f} size={decision.position_size_pct:.2f}")
                return decision
            
        except Exception as e:
            logger.error(f"AI Analyst error for {symbol}: {e}")
        
        return None
    
    def _build_prompt(
        self,
        symbol: str,
        quant_signals: Dict[str, float],
        structure: MarketStructure,
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
    ) -> str:
        """Build comprehensive analysis prompt"""
        
        # Format quant signals
        signal_lines = []
        for agent, sig in quant_signals.items():
            direction = "LONG" if sig > 0 else "SHORT" if sig < 0 else "NEUTRAL"
            signal_lines.append(f"  {agent}: {sig:+.3f} ({direction})")
        
        signals_text = "\n".join(signal_lines) if signal_lines else "  No signals"
        
        btc_corr_str = f"{btc_correlation:+.2f}" if btc_correlation is not None else "N/A"
        fear_greed_str = f"{fear_greed}/100" if fear_greed is not None else "N/A"
        news_str = f"{news_sentiment:+.2f}" if news_sentiment is not None else "N/A"
        sup = structure.key_levels.get('support')
        res = structure.key_levels.get('resistance')
        support_str = f"${sup:,.2f}" if sup is not None else "N/A"
        resistance_str = f"${res:,.2f}" if res is not None else "N/A"
        
        prompt = f"""You are an expert crypto futures trader with 15+ years experience. Analyze {symbol} and provide a trading decision.

CURRENT MARKET DATA:
- Symbol: {symbol}
- Current Price: ${price:,.2f}
- ATR (14): ${atr:,.2f}
- 24h Volume: ${volume_24h:,.0f}
- Funding Rate: {funding_rate:.4%} (8h)
- Open Interest: ${open_interest:,.0f}
- BTC Correlation: {btc_corr_str}
- Fear & Greed Index: {fear_greed_str}
- News Sentiment: {news_str}

QUANTITATIVE SIGNALS (from 4 agents):
{signals_text}
HTF Bias (15m): {htf_bias:+.2f} (negative=bearish, positive=bullish)

MARKET STRUCTURE:
- HTF Trend: {structure.htf_trend}
- HTF Structure: {structure.htf_structure}
- LTF Structure: {structure.ltf_structure}
- Key Levels: Support={support_str}, Resistance={resistance_str}
- Order Flow Bias: {structure.order_flow_bias:+.2f}
- Liquidity Zones: {[f'${z:,.0f}' for z in structure.liquidity_zones] if structure.liquidity_zones else 'N/A'}

REGIME: {regime.value}

YOUR TASK: Provide a JSON decision with EXACTLY this structure:
{{
  "direction": "long" | "short" | "neutral",
  "confidence": 0.0-1.0,
  "position_size_pct": 0.0-1.0,
  "entry_low": price,
  "entry_high": price,
  "stop_loss": price,
  "take_profit_1": price,
  "take_profit_2": price,
  "reasoning": "2-3 sentence concise reasoning",
  "key_factors": ["factor1", "factor2", "factor3"],
  "risk_factors": ["risk1", "risk2"],
  "timeframe_alignment": true/false
}}

RULES:
1. Direction MUST align with HTF trend unless strong reversal setup
2. Confidence > 0.7 only for high-conviction setups (structure + flow + quant aligned)
3. Position size: 0.3-0.5 for normal, 0.6-0.8 for high conviction, 0.9-1.0 for exceptional
4. Stop loss: 1-1.5 ATR from entry
5. TP1: 1.5-2R, TP2: 2.5-3.5R
6. entry_zone should be tight (0.1-0.3% range)
7. If neutral, set confidence=0, position_size_pct=0
8. Consider funding rate: avoid long if funding > 0.01% (overheated), avoid short if funding < -0.01%
9. Consider OI: rising OI + price = trend continuation, falling OI + price = exhaustion
10. BTC correlation: if > 0.7, follow BTC lead; if < 0.3, idiosyncratic move

Be decisive. No hedging language. Return ONLY valid JSON."""
        return prompt
    
    def _parse_response(
        self,
        response_text: str,
        symbol: str,
        price: float,
        atr: float,
        regime: MarketRegime
    ) -> Optional[AnalystDecision]:
        """Parse LLM response into AnalystDecision"""
        try:
            data = json.loads(response_text)
            
            direction = data.get('direction', 'neutral')
            if direction not in ('long', 'short', 'neutral'):
                return None
            
            confidence = max(0.0, min(1.0, float(data.get('confidence', 0))))
            position_size_pct = max(0.0, min(1.0, float(data.get('position_size_pct', 0))))
            
            entry_low = float(data.get('entry_low', price * 0.999))
            entry_high = float(data.get('entry_high', price * 1.001))
            stop_loss = float(data.get('stop_loss', 0))
            tp1 = float(data.get('take_profit_1', 0))
            tp2 = float(data.get('take_profit_2', 0))
            
            # Validate stops/targets
            if direction == 'long':
                if stop_loss >= entry_low or stop_loss <= 0:
                    stop_loss = entry_low - atr * 1.2
                if tp1 <= entry_high:
                    tp1 = entry_high + atr * 2.0
                if tp2 <= tp1:
                    tp2 = tp1 + atr * 2.0
            elif direction == 'short':
                if stop_loss <= entry_high or stop_loss <= 0:
                    stop_loss = entry_high + atr * 1.2
                if tp1 >= entry_low:
                    tp1 = entry_low - atr * 2.0
                if tp2 >= tp1:
                    tp2 = tp1 - atr * 2.0
            
            return AnalystDecision(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                position_size_pct=position_size_pct,
                entry_zone=(entry_low, entry_high),
                stop_loss=stop_loss,
                take_profit_1=tp1,
                take_profit_2=tp2,
                reasoning=data.get('reasoning', ''),
                key_factors=data.get('key_factors', []),
                risk_factors=data.get('risk_factors', []),
                regime=regime,
                timeframe_alignment=data.get('timeframe_alignment', False)
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse AI Analyst response: {e}")
            return None


def create_ai_analyst(config: Dict) -> AIAnalystAgent:
    return AIAnalystAgent(config)