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
            
        else:
            raise IndicatorError(f"Unsupported indicator: '{name}'")
