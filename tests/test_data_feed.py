from datetime import datetime
import pandas as pd
import pytest

from src.engine.data_feed import BaseDataProvider, DataFeed, DataProviderError
from src.engine.providers.yfinance_provider import YFinanceProvider


class MockDataProvider(BaseDataProvider):
    """Mock provider for deterministic testing without network calls."""

    def __init__(self, sample_df: pd.DataFrame):
        self.sample_df = sample_df
        self.call_count = 0

    def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
    ) -> pd.DataFrame:
        self.call_count += 1
        return self.sample_df.copy()


@pytest.fixture
def sample_daily_candles() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2024-01-05", freq="D", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 101.0, 105.0, 107.0],
            "high": [103.0, 104.0, 106.0, 108.0, 110.0],
            "low": [99.0, 100.0, 100.0, 104.0, 106.0],
            "close": [102.0, 101.0, 105.0, 107.0, 109.0],
            "volume": [1000, 1200, 1500, 1100, 2000],
        },
        index=dates,
    )


def test_parquet_cache_write_and_read(tmp_path, sample_daily_candles):
    mock = MockDataProvider(sample_daily_candles)
    feed = DataFeed(provider=mock, cache_dir=str(tmp_path))

    # First fetch: should trigger provider and write .parquet file
    df1 = feed.get_candles("NESTLEIND", "NSE", "1d", "2024-01-01", "2024-01-05")
    assert mock.call_count == 1
    assert len(df1) == 5

    # Check parquet file was actually created on disk
    parquet_files = list(tmp_path.glob("*.parquet"))
    assert len(parquet_files) == 1
    assert "NESTLEIND_NSE_1d_2024-01-01_2024-01-05.parquet" in parquet_files[0].name

    # Second fetch: should hit parquet cache and NOT call provider
    df2 = feed.get_candles("NESTLEIND", "NSE", "1d", "2024-01-01", "2024-01-05")
    assert mock.call_count == 1  # Still 1! Cache hit!
    assert len(df2) == 5
    assert df1.equals(df2)


def test_force_refresh_bypasses_cache(tmp_path, sample_daily_candles):
    mock = MockDataProvider(sample_daily_candles)
    feed = DataFeed(provider=mock, cache_dir=str(tmp_path))

    feed.get_candles("NESTLEIND", "NSE", "1d", "2024-01-01", "2024-01-05")
    assert mock.call_count == 1

    # Force refresh must call provider again
    feed.get_candles("NESTLEIND", "NSE", "1d", "2024-01-01", "2024-01-05", force_refresh=True)
    assert mock.call_count == 2


def test_ohlcv_resampling_accuracy():
    # 5 one-minute bars
    dates = pd.date_range("2024-01-01 09:15:00", periods=5, freq="1min", tz="Asia/Kolkata")
    df_1m = pd.DataFrame(
        {
            "open": [100.0, 101.0, 103.0, 105.0, 104.0],
            "high": [102.0, 104.0, 105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 102.0, 104.0, 103.0],
            "close": [101.0, 103.0, 105.0, 104.0, 106.0],
            "volume": [10, 20, 30, 40, 50],
        },
        index=dates,
    )

    # Resample to 5m
    resampled = DataFeed.resample_candles(df_1m, "5m")

    assert len(resampled) == 1
    candle = resampled.iloc[0]
    # open must be first bar's open (100.0)
    assert candle["open"] == 100.0
    # high must be max across all bars (107.0)
    assert candle["high"] == 107.0
    # low must be min across all bars (99.0)
    assert candle["low"] == 99.0
    # close must be last bar's close (106.0)
    assert candle["close"] == 106.0
    # volume must be total sum (150)
    assert candle["volume"] == 150


def test_missing_column_raises_error(tmp_path):
    # Provider returns DataFrame without 'close'
    bad_df = pd.DataFrame({"open": [100.0], "high": [105.0], "low": [95.0], "volume": [100]})
    mock = MockDataProvider(bad_df)
    feed = DataFeed(provider=mock, cache_dir=str(tmp_path))

    with pytest.raises(DataProviderError, match="Missing required candle column: 'close'"):
        feed.get_candles("BAD_DATA")


def test_yfinance_ticker_mapping():
    provider = YFinanceProvider()

    # Index mapping
    assert provider._resolve_ticker("NIFTY", "NSE") == "^NSEI"
    assert provider._resolve_ticker("BANKNIFTY", "NSE") == "^NSEBANK"

    # Equity mapping
    assert provider._resolve_ticker("NESTLEIND", "NSE") == "NESTLEIND.NS"
    assert provider._resolve_ticker("RELIANCE", "BSE") == "RELIANCE.BO"

    # Already formatted tickers
    assert provider._resolve_ticker("TCS.NS", "NSE") == "TCS.NS"
    assert provider._resolve_ticker("^NSEI", "NSE") == "^NSEI"
