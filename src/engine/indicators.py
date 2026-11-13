"""
Technical Indicator Computation Engine.

Provides pure, vectorized indicator calculations without future data leakage.
"""

from typing import Dict, Any, Union
import numpy as np
import pandas as pd
from src.schema.strategy import IndicatorDefinition


class IndicatorError(Exception):
    """Exception raised when indicator calculation fails or invalid parameters are provided."""
    pass


def sma(df: pd.DataFrame, period: int = 20, field: str = "close") -> pd.Series:
    """Simple Moving Average (SMA)."""
    if field not in df.columns:
        raise IndicatorError(f"Field '{field}' not found in dataframe columns")
    return df[field].rolling(window=period, min_periods=period).mean()


def ema(df: pd.DataFrame, period: int = 20, field: str = "close") -> pd.Series:
    """Exponential Moving Average (EMA)."""
    if field not in df.columns:
        raise IndicatorError(f"Field '{field}' not found in dataframe columns")
    return df[field].ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) using Wilder's Smoothing.
    
    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
    """
    for col in ["high", "low", "close"]:
        if col not in df.columns:
            raise IndicatorError(f"Required column '{col}' missing for ATR calculation")
            
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    
    tr0 = high - low
    tr1 = (high - prev_close).abs()
    tr2 = (low - prev_close).abs()
    
    true_range = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
    # Wilder's Smoothing: ewm with alpha = 1 / period
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def rsi(df: pd.DataFrame, period: int = 14, field: str = "close") -> pd.Series:
    """
    Relative Strength Index (RSI) using Wilder's smoothed averages.
    Bounded between 0 and 100.
    """
    if field not in df.columns:
        raise IndicatorError(f"Field '{field}' not found in dataframe columns")
        
    delta = df[field].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Wilder's smoothing
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    
    # Where avg_loss is 0, RSI is 100 (if avg_gain > 0) or 50 (if avg_gain == 0)
    rsi_series = rsi_series.fillna(100.0)
    rsi_series.loc[(avg_gain == 0) & (avg_loss == 0)] = 50.0
    
    return rsi_series


def vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume Weighted Average Price (VWAP).
    Resets at the start of each daily trading session.
    """
    for col in ["high", "low", "close", "volume"]:
        if col not in df.columns:
            raise IndicatorError(f"Required column '{col}' missing for VWAP calculation")
            
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_volume = typical_price * df["volume"]
    
    # Session date grouping
    if not isinstance(df.index, pd.DatetimeIndex):
        raise IndicatorError("VWAP calculation requires a DatetimeIndex to identify daily sessions")
        
    dates = df.index.normalize()
    
    cum_tp_vol = tp_volume.groupby(dates).cumsum()
    cum_vol = df["volume"].groupby(dates).cumsum()
    
    vwap_series = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap_series.fillna(typical_price)


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    Supertrend Indicator.
    
    Returns a DataFrame with columns:
    - 'supertrend': The active trailing stop line
    - 'direction': 1 for bullish (price above supertrend), -1 for bearish
    """
    for col in ["high", "low", "close"]:
        if col not in df.columns:
            raise IndicatorError(f"Required column '{col}' missing for Supertrend calculation")
            
    atr_vals = atr(df, period=period)
    hl2 = (df["high"] + df["low"]) / 2.0
    
    upper_basic = hl2 + (multiplier * atr_vals)
    lower_basic = hl2 - (multiplier * atr_vals)
    
    n = len(df)
    upper_band = np.zeros(n)
    lower_band = np.zeros(n)
    supertrend_vals = np.zeros(n)
    direction = np.ones(n, dtype=int)  # 1 for bull, -1 for bear
    
    close_vals = df["close"].values
    ub_vals = upper_basic.values
    lb_vals = lower_basic.values
    
    for i in range(1, n):
        # Upper band adjustment
        if ub_vals[i] < upper_band[i-1] or close_vals[i-1] > upper_band[i-1]:
            upper_band[i] = ub_vals[i]
        else:
            upper_band[i] = upper_band[i-1]
            
        # Lower band adjustment
        if lb_vals[i] > lower_band[i-1] or close_vals[i-1] < lower_band[i-1]:
            lower_band[i] = lb_vals[i]
        else:
            lower_band[i] = lower_band[i-1]
            
        # Trend direction
        if direction[i-1] == 1:
            if close_vals[i] < lower_band[i]:
                direction[i] = -1
                supertrend_vals[i] = upper_band[i]
            else:
                direction[i] = 1
                supertrend_vals[i] = lower_band[i]
        else:
            if close_vals[i] > upper_band[i]:
                direction[i] = 1
                supertrend_vals[i] = lower_band[i]
            else:
                direction[i] = -1
                supertrend_vals[i] = upper_band[i]
                
    # If first bar, initialize
    if n > 0:
        supertrend_vals[0] = lower_band[0] if ub_vals[0] else close_vals[0]
        
    return pd.DataFrame(
        {
            "supertrend": supertrend_vals,
            "direction": direction,
        },
        index=df.index,
    )


def sma_envelope(
    df: pd.DataFrame, 
    period: int = 200, 
    atr_period: int = 14, 
    multiplier: float = 1.5, 
    field: str = "close"
) -> pd.DataFrame:
    """
    SMA Envelope / ATR Dead-Zone Bands around SMA.
    
    Returns a DataFrame with columns:
    - 'upper': sma + (multiplier * atr)
    - 'lower': sma - (multiplier * atr)
    - 'middle': sma
    """
    for col in ["high", "low", "close"]:
        if col not in df.columns:
            raise IndicatorError(f"Required column '{col}' missing for SMA Envelope calculation")
            
    mid = sma(df, period=period, field=field)
    vol = atr(df, period=atr_period)
    
    upper = mid + (multiplier * vol)
    lower = mid - (multiplier * vol)
    
    return pd.DataFrame(
        {
            "upper": upper,
            "lower": lower,
            "middle": mid,
        },
        index=df.index,
    )


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index (ADX) by J. Welles Wilder Jr.
    
    Returns a DataFrame with columns:
    - 'adx': Smoothed trend strength (0 to 100)
    - 'plus_di': +DI positive directional indicator
    - 'minus_di': -DI negative directional indicator
    """
    for col in ["high", "low", "close"]:
        if col not in df.columns:
            raise IndicatorError(f"Required column '{col}' missing for ADX calculation")
            
    high = df["high"]
    low = df["low"]
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    atr_vals = atr(df, period=period)
    
    # Wilder's smoothing (alpha = 1 / period)
    plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    
    plus_di = 100.0 * (plus_dm_s / atr_vals.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm_s / atr_vals.replace(0, np.nan))
    
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    
    dx = 100.0 * (di_diff / di_sum.replace(0, np.nan))
    dx = dx.fillna(0.0)
    
    adx_s = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    
    return pd.DataFrame(
        {
            "adx": adx_s.fillna(0.0),
            "plus_di": plus_di.fillna(0.0),
            "minus_di": minus_di.fillna(0.0),
        },
        index=df.index,
    )


class IndicatorEngine:
    """
    Registry and Dispatcher for Technical Indicators.
    """

    @classmethod
    def compute(cls, df: pd.DataFrame, indicator: IndicatorDefinition) -> pd.Series:
        """
        Compute indicator for a given IndicatorDefinition.
        
        Returns a single pd.Series representing the indicator output.
        """
        name = indicator.name.upper()
        params = indicator.params or {}
        
        if name == "SMA":
            period = int(params.get("period", 20))
            field = str(params.get("field", "close"))
            return sma(df, period=period, field=field)
            
        elif name == "EMA":
            period = int(params.get("period", 20))
            field = str(params.get("field", "close"))
            return ema(df, period=period, field=field)
            
        elif name == "RSI":
            period = int(params.get("period", 14))
            field = str(params.get("field", "close"))
            return rsi(df, period=period, field=field)
            
        elif name == "VWAP":
            return vwap(df)
            
        elif name == "ATR":
            period = int(params.get("period", 14))
            return atr(df, period=period)
            
        elif name == "SUPERTREND":
            period = int(params.get("period", 10))
            multiplier = float(params.get("multiplier", 3.0))
            st_df = supertrend(df, period=period, multiplier=multiplier)
            # Default to the 'supertrend' line
            field = params.get("field", "supertrend")
            if field in st_df.columns:
                return st_df[field]
            return st_df["supertrend"]
            
        elif name in ("SMA_ENVELOPE", "SMA_BAND"):
            period = int(params.get("period", 200))
            atr_period = int(params.get("atr_period", 14))
            multiplier = float(params.get("multiplier", 1.5))
            field = str(params.get("field", "close"))
            band = str(params.get("band", "upper")).lower()
            env_df = sma_envelope(df, period=period, atr_period=atr_period, multiplier=multiplier, field=field)
            if band in env_df.columns:
                return env_df[band]
            return env_df["upper"]
            
        elif name == "ADX":
            period = int(params.get("period", 14))
            field = str(params.get("field", "adx")).lower()
            adx_df = adx(df, period=period)
            if field in adx_df.columns:
                return adx_df[field]
            return adx_df["adx"]
            
        else:
            raise IndicatorError(f"Unsupported indicator: '{name}'")
