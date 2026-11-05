"""
Unit Tests for DhanHQProvider.

Verifies:
1. Credential validation & error handling
2. Symbol to Security ID resolution
3. Response parsing & UTC-to-IST timezone conversion
4. Column structure validation
5. Integration with DataFeed Parquet caching
"""

import pytest
import os
from unittest.mock import MagicMock
import pandas as pd
import numpy as np

from src.engine.providers.dhan_provider import DhanHQProvider
from src.engine.data_feed import DataFeed, DataProviderError


def test_dhan_provider_missing_credentials_raises_error(monkeypatch):
    """When no credentials are provided or in env, DhanHQProvider must raise DataProviderError."""
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)

    with pytest.raises(DataProviderError, match="DhanHQ credentials missing"):
        DhanHQProvider(client_id=None, access_token=None)


def test_dhan_symbol_resolution():
    """Verify built-in security resolution for key symbols."""
    mock_client = MagicMock()
    provider = DhanHQProvider(client_instance=mock_client)

    sec_nestle = provider._resolve_security("NESTLEIND", "NSE")
    assert sec_nestle["security_id"] == "17963"
    assert sec_nestle["exchange_segment"] == "NSE_EQ"
    assert sec_nestle["instrument_type"] == "EQUITY"

    sec_reliance = provider._resolve_security("RELIANCE", "NSE")
    assert sec_reliance["security_id"] == "2885"

    sec_nifty = provider._resolve_security("NIFTY", "NSE")
    assert sec_nifty["security_id"] == "13"
    assert sec_nifty["exchange_segment"] == "IDX_I"

    with pytest.raises(DataProviderError, match="not found in DhanHQ security resolver"):
        provider._resolve_security("UNKNOWN_TICKER_XYZ", "NSE")


def test_dhan_unsupported_interval_raises_error():
    """Verify that unsupported interval strings raise DataProviderError."""
    mock_client = MagicMock()
    provider = DhanHQProvider(client_instance=mock_client)

    with pytest.raises(DataProviderError, match="Unsupported interval"):
        provider.fetch_candles("NESTLEIND", interval="2h")


def test_dhan_fetch_candles_success():
    """Verify parsing of Dhan JSON columnar response into a valid IST DataFrame."""
    mock_client = MagicMock()
    # Mock Dhan API response: 2 candles (epoch seconds: 1727754300, 1727755200)
    mock_response = {
        "status": "success",
        "remarks": "",
        "data": {
            "open": [1390.0, 1395.0],
            "high": [1398.0, 1400.0],
            "low": [1388.0, 1392.0],
            "close": [1395.0, 1398.5],
            "volume": [1500, 2300],
            "timestamp": [1727754300, 1727755200],  # 2024-10-01 09:15:00 IST & 09:30:00 IST
        },
    }
    mock_client.intraday_minute_data.return_value = mock_response

    provider = DhanHQProvider(client_instance=mock_client)
    df = provider.fetch_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")

    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert str(df.index.tz) == "Asia/Kolkata"
    assert df["open"].iloc[0] == 1390.0
    assert df["close"].iloc[1] == 1398.5
    assert df.index.name == "datetime"


def test_dhan_fetch_candles_api_failure():
    """When Dhan API returns failure status (e.g. DH-902), raise informative DataProviderError."""
    mock_client = MagicMock()
    mock_client.intraday_minute_data.return_value = {
        "status": "failure",
        "remarks": {
            "error_code": "DH-902",
            "error_type": "Invalid_Access",
            "error_message": "This API requires a Data APIs Plan. Current plan: Free Plan",
        },
    }

    provider = DhanHQProvider(client_instance=mock_client)
    with pytest.raises(DataProviderError, match="DH-902"):
        provider.fetch_candles("NESTLEIND", interval="15m")


def test_dhan_fetch_candles_empty_data():
    """When Dhan returns 0 candles, raise DataProviderError."""
    mock_client = MagicMock()
    mock_client.intraday_minute_data.return_value = {
        "status": "success",
        "remarks": "",
        "data": {"open": [], "high": [], "low": [], "close": [], "volume": [], "timestamp": []},
    }

    provider = DhanHQProvider(client_instance=mock_client)
    with pytest.raises(DataProviderError, match="returned 0 candles"):
        provider.fetch_candles("NESTLEIND", interval="15m")


def test_datafeed_integration_with_dhan_provider(tmp_path):
    """Verify that DataFeed caches DhanHQProvider candles to Parquet seamlessly."""
    mock_client = MagicMock()
    mock_client.intraday_minute_data.return_value = {
        "status": "success",
        "remarks": "",
        "data": {
            "open": [100.0, 105.0],
            "high": [110.0, 112.0],
            "low": [98.0, 104.0],
            "close": [105.0, 110.0],
            "volume": [500, 800],
            "timestamp": [1727754300, 1727755200],
        },
    }

    provider = DhanHQProvider(client_instance=mock_client)
    feed = DataFeed(provider=provider, cache_dir=str(tmp_path))

    # First fetch: calls provider
    df1 = feed.get_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")
    assert len(df1) == 2
    assert mock_client.intraday_minute_data.call_count == 1

    # Second fetch: served from Parquet cache (mock not called again)
    df2 = feed.get_candles("NESTLEIND", interval="15m", start_date="2024-10-01", end_date="2024-10-01")
    assert len(df2) == 2
    assert mock_client.intraday_minute_data.call_count == 1  # Still 1! Zero network call.
    pd.testing.assert_frame_equal(df1, df2)
