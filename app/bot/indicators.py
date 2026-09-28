"""
Technical Indicators - Optimized pandas implementations
"""
import pandas as pd
import numpy as np
from typing import Dict, Any


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average"""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average"""
    return series.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range"""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> Dict[str, pd.Series]:
    """Average Directional Index with +DI and -DI"""
    high = df['high']
    low = df['low']
    close = df['close']
    
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    
    tr = atr(df, period)
    
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / tr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / tr)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = dx.rolling(window=period).mean()
    
    return {'adx': adx_val, 'plus_di': plus_di, 'minus_di': minus_di}


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
    """MACD"""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {'macd': macd_line, 'signal': signal_line, 'histogram': histogram}


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2) -> Dict[str, pd.Series]:
    """Bollinger Bands"""
    mid = sma(series, period)
    std = series.rolling(window=period).std()
    return {
        'upper': mid + std_dev * std,
        'middle': mid,
        'lower': mid - std_dev * std
    }


def stoch_rsi(series: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Dict[str, pd.Series]:
    """Stochastic RSI"""
    rsi_val = rsi(series, period)
    min_rsi = rsi_val.rolling(window=period).min()
    max_rsi = rsi_val.rolling(window=period).max()
    stoch = (rsi_val - min_rsi) / (max_rsi - min_rsi)
    k = stoch.rolling(window=smooth_k).mean() * 100
    d = k.rolling(window=smooth_d).mean()
    return {'k': k, 'd': d}


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3) -> Dict[str, pd.Series]:
    """SuperTrend indicator"""
    atr_val = atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    
    upper = hl2 + multiplier * atr_val
    lower = hl2 - multiplier * atr_val
    
    trend = pd.Series(1, index=df.index)
    supertrend_val = pd.Series(index=df.index)
    
    for i in range(1, len(df)):
        if df['close'].iloc[i] > upper.iloc[i-1]:
            trend.iloc[i] = 1
        elif df['close'].iloc[i] < lower.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]
            
            if trend.iloc[i] == 1 and lower.iloc[i] < lower.iloc[i-1]:
                lower.iloc[i] = lower.iloc[i-1]
            if trend.iloc[i] == -1 and upper.iloc[i] > upper.iloc[i-1]:
                upper.iloc[i] = upper.iloc[i-1]
        
        supertrend_val.iloc[i] = lower.iloc[i] if trend.iloc[i] == 1 else upper.iloc[i]
    
    return {'supertrend': supertrend_val, 'trend': trend, 'upper': upper, 'lower': lower}


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price"""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()


def all_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Compute all indicators for a dataframe"""
    df = df.copy()
    
    atr_period = config.get('atr_period', 14)
    adx_period = config.get('atr_period', 14)
    
    # Trend
    df['ema_fast'] = ema(df['close'], 9)
    df['ema_slow'] = ema(df['close'], 21)
    df['ema_trend'] = ema(df['close'], 50)
    df['ema_200'] = ema(df['close'], 200)
    
    # Momentum
    df['rsi'] = rsi(df['close'], 14)
    df['rsi_7'] = rsi(df['close'], 7)
    
    # Volatility
    df['atr'] = atr(df, atr_period)
    adx_data = adx(df, adx_period)
    df['adx'] = adx_data['adx']
    df['plus_di'] = adx_data['plus_di']
    df['minus_di'] = adx_data['minus_di']
    
    # MACD
    macd_data = macd(df['close'])
    df['macd'] = macd_data['macd']
    df['macd_signal'] = macd_data['signal']
    df['macd_hist'] = macd_data['histogram']
    
    # Bollinger Bands
    bb = bollinger_bands(df['close'], 20, 2)
    df['bb_upper'] = bb['upper']
    df['bb_middle'] = bb['middle']
    df['bb_lower'] = bb['lower']
    df['bb_width'] = (bb['upper'] - bb['lower']) / bb['middle']
    
    # Stochastic RSI
    stoch = stoch_rsi(df['close'])
    df['stoch_rsi_k'] = stoch['k']
    df['stoch_rsi_d'] = stoch['d']
    
    # SuperTrend
    st = supertrend(df, 10, 3)
    df['supertrend'] = st['supertrend']
    df['st_trend'] = st['trend']
    
    # VWAP
    df['vwap'] = vwap(df)
    
    # Price action
    df['body'] = (df['close'] - df['open']).abs()
    df['range'] = df['high'] - df['low']
    df['body_ratio'] = df['body'] / df['range'].replace(0, np.nan)
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    
    return df


def detect_regime(df: pd.DataFrame) -> str:
    """Detect market regime from latest candle"""
    if len(df) < 50:
        return 'unknown'
    
    last = df.iloc[-1]
    
    # Trend strength
    adx = last.get('adx', 0)
    ema_fast = last.get('ema_fast', 0)
    ema_slow = last.get('ema_slow', 0)
    ema_trend = last.get('ema_trend', 0)
    
    # Volatility
    bb_width = last.get('bb_width', 0)
    atr_ratio = last.get('atr', 0) / last.get('close', 1) if last.get('close', 0) > 0 else 0
    
    # Regime logic
    if adx > 25 and ema_fast > ema_slow > ema_trend:
        return 'strong_trend'
    elif adx > 25 and ema_fast < ema_slow < ema_trend:
        return 'strong_trend'
    elif adx > 15:
        return 'weak_trend'
    elif bb_width < 0.05 and atr_ratio < 0.01:
        return 'quiet_range'
    elif atr_ratio > 0.03:
        return 'volatile_range'
    else:
        return 'range'