import pytest
import numpy as np
import pandas as pd
from src.schema.strategy import IndicatorDefinition
from src.engine.indicators import (
    sma, ema, rsi, vwap, atr, supertrend, IndicatorEngine, IndicatorError
)


@pytest.fixture
def sample_ohlcv():
    dates = pd.date_range("2024-01-01 09:15", periods=50, freq="15min")
    np.random.seed(42)
    base_price = 100.0
    returns = np.random.normal(0, 0.01, size=len(dates))
    close = base_price * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(np.random.normal(0, 0.005, size=len(dates))))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, size=len(dates))))
    open_p = (high + low) / 2.0
    volume = np.random.randint(100, 1000, size=len(dates))
    
    return pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def test_sma_calculation(sample_ohlcv):
    period = 10
    result = sma(sample_ohlcv, period=period)
    assert len(result) == len(sample_ohlcv)
    # Warmup NaNs
    assert result.iloc[:period-1].isna().all()
    # Exactly matches manual mean
    expected = sample_ohlcv["close"].iloc[:period].mean()
    assert np.isclose(result.iloc[period-1], expected)


def test_ema_calculation(sample_ohlcv):
    period = 10
    result = ema(sample_ohlcv, period=period)
    assert len(result) == len(sample_ohlcv)
    assert not result.isna().any()


def test_rsi_bounds(sample_ohlcv):
    period = 14
    result = rsi(sample_ohlcv, period=period)
    # Exclude warmup NaNs
    valid = result.dropna()
    assert (valid >= 0.0).all()
    assert (valid <= 100.0).all()


def test_vwap_intraday_reset():
    # 2 separate days
    day1 = pd.date_range("2024-01-01 09:15", "2024-01-01 15:30", freq="15min")
    day2 = pd.date_range("2024-01-02 09:15", "2024-01-02 15:30", freq="15min")
    all_dates = day1.append(day2)
    
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 101.0,
            "volume": 1000,
        },
        index=all_dates,
    )
    # On day 2 bar 1, typical price is (102+98+101)/3 = 100.3333...
    res = vwap(df)
    tp = (102.0 + 98.0 + 101.0) / 3.0
    assert np.isclose(res.loc[day2[0]], tp)


def test_atr_positive(sample_ohlcv):
    result = atr(sample_ohlcv, period=14)
    valid = result.dropna()
    assert (valid > 0).all()


def test_supertrend_structure(sample_ohlcv):
    res = supertrend(sample_ohlcv, period=10, multiplier=3.0)
    assert "supertrend" in res.columns
    assert "direction" in res.columns
    assert set(res["direction"].unique()).issubset({1, -1})


def test_indicator_engine_dispatch(sample_ohlcv):
    ind_def = IndicatorDefinition(name="SMA", params={"period": 20, "field": "close"})
    res = IndicatorEngine.compute(sample_ohlcv, ind_def)
    assert len(res) == len(sample_ohlcv)

    with pytest.raises(IndicatorError, match="Unsupported indicator"):
        IndicatorEngine.compute(sample_ohlcv, IndicatorDefinition(name="UNKNOWN_IND"))
