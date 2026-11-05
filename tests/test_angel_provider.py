"""
Unit Tests for AngelOneProvider.

Verifies:
1. Credential validation & error handling
2. Symbol to token resolution
3. Response parsing & IST timezone conversion
4. Column structure validation
5. Integration with DataFeed Parquet caching
"""

import pytest
from unittest.mock import MagicMock
import pandas as pd

from src.engine.providers.angel_provider import AngelOneProvider
from src.engine.data_feed import DataFeed, DataProviderError


def test_angel_provider_missing_credentials_raises_error(monkeypatch):
    """When no credentials are provided or in env, AngelOneProvider must raise DataProviderError."""
    monkeypatch.delenv("ANGEL_API_KEY", raising=False)
    monkeypatch.delenv("ANGEL_CLIENT_CODE", raising=False)
    monkeypatch.delenv("ANGEL_PIN", raising=False)
    monkeypatch.delenv("ANGEL_TOTP_SECRET", raising=False)

    with pytest.raises(DataProviderError, match="Angel One credentials missing"):
        AngelOneProvider()


def test_angel_token_resolution():
    """Verify built-in token resolution for key symbols."""
    mock_client = MagicMock()
    provider = AngelOneProvider(smart_connect_instance=mock_client)

    assert provider._resolve_token("NESTLEIND", "NSE") == "17963"
    assert provider._resolve_token("RELIANCE", "NSE") == "2885"
    assert provider._resolve_token("NIFTY", "NSE") == "99926000"
    assert provider._resolve_token("BANKNIFTY", "NSE") == "99926009"

    with pytest.raises(DataProviderError, match="not found in Angel One token resolver"):
        provider._resolve_token("UNKNOWN_TICKER_XYZ", "NSE")


def test_angel_unsupported_interval_raises_error():
    """Verify that unsupported interval strings raise DataProviderError."""
    mock_client = MagicMock()
    provider = AngelOneProvider(smart_connect_instance=mock_client)

    with pytest.raises(DataProviderError, match="Unsupported interval"):
        provider.fetch_candles("NESTLEIND", interval="2h")


def test_angel_fetch_candles_success():
    """Verify parsing of Angel One list-of-lists response into a valid IST DataFrame."""
    mock_client = MagicMock()
    mock_response = {
        "status": True,
        "message": "SUCCESS",
        "errorcode": "",
        "data": [
            ["2024-10-01T09:15:00+05:30", 1390.0, 1398.0, 1388.0, 1395.0, 1500],
            ["2024-10-01T09:30:00+05:30", 1395.0, 1400.0, 1392.0, 1398.5, 2300],
        ],
    }
    mock_client.getCandleData.return_value = mock_response

    provider = AngelOneProvider(smart_connect_instance=mock_client)
    df = provider.fetch_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")

    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "Asia/Kolkata"
    assert df["open"].iloc[0] == 1390.0
    assert df["close"].iloc[1] == 1398.5
    assert df.index.name == "datetime"


def test_angel_fetch_candles_failure_status():
    """When Angel One API returns failure status, raise informative DataProviderError."""
    mock_client = MagicMock()
    mock_client.getCandleData.return_value = {
        "status": False,
        "message": "Invalid Token or Session Expired",
        "errorcode": "AG8001",
    }

    provider = AngelOneProvider(smart_connect_instance=mock_client)
    with pytest.raises(DataProviderError, match="getCandleData failed"):
        provider.fetch_candles("NESTLEIND", interval="15m")


def test_angel_fetch_candles_empty_data():
    """When Angel One returns 0 candles, raise DataProviderError."""
    mock_client = MagicMock()
    mock_client.getCandleData.return_value = {
        "status": True,
        "message": "SUCCESS",
        "data": [],
    }

    provider = AngelOneProvider(smart_connect_instance=mock_client)
    with pytest.raises(DataProviderError, match="returned 0 candles"):
        provider.fetch_candles("NESTLEIND", interval="15m")


def test_datafeed_integration_with_angel_provider(tmp_path):
    """Verify that DataFeed caches AngelOneProvider candles to Parquet seamlessly."""
    mock_client = MagicMock()
    mock_client.getCandleData.return_value = {
        "status": True,
        "message": "SUCCESS",
        "data": [
            ["2024-10-01T09:15:00+05:30", 100.0, 110.0, 98.0, 105.0, 500],
            ["2024-10-01T09:30:00+05:30", 105.0, 112.0, 104.0, 110.0, 800],
        ],
    }

    provider = AngelOneProvider(smart_connect_instance=mock_client)
    feed = DataFeed(provider=provider, cache_dir=str(tmp_path))

    # First fetch: queries provider
    df1 = feed.get_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")
    assert len(df1) == 2
    assert mock_client.getCandleData.call_count == 1

    # Second fetch: served from Parquet cache (mock not called again)
    df2 = feed.get_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")
    assert len(df2) == 2
    assert mock_client.getCandleData.call_count == 1
    pd.testing.assert_frame_equal(df1, df2)
