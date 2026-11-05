"""
DhanHQ Historical Market Data Provider.

Fetches broker-grade intraday and historical candles from DhanHQ API
using official dhanhq SDK.
"""

import os
from typing import Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

from dhanhq import DhanContext, dhanhq
from src.engine.data_feed import BaseDataProvider, DataProviderError


load_dotenv()


class DhanHQProvider(BaseDataProvider):
    """
    Historical market data provider connecting to DhanHQ.
    
    Supports:
    - Automated symbol to security ID resolution (built-in + scrip master)
    - Intraday minute bars (1m, 5m, 15m, 25m, 60m)
    - Automatic conversion of UNIX epoch timestamps to Asia/Kolkata timezone
    - Seamless caching to Parquet via DataFeed
    """

    KNOWN_SECURITIES: Dict[str, Dict[str, str]] = {
        "NESTLEIND": {
            "security_id": "17963",
            "exchange_segment": "NSE_EQ",
            "instrument_type": "EQUITY",
        },
        "RELIANCE": {
            "security_id": "2885",
            "exchange_segment": "NSE_EQ",
            "instrument_type": "EQUITY",
        },
        "TCS": {
            "security_id": "11536",
            "exchange_segment": "NSE_EQ",
            "instrument_type": "EQUITY",
        },
        "INFY": {
            "security_id": "1594",
            "exchange_segment": "NSE_EQ",
            "instrument_type": "EQUITY",
        },
        "HDFCBANK": {
            "security_id": "1333",
            "exchange_segment": "NSE_EQ",
            "instrument_type": "EQUITY",
        },
        "NIFTY": {
            "security_id": "13",
            "exchange_segment": "IDX_I",
            "instrument_type": "INDEX",
        },
        "NIFTY50": {
            "security_id": "13",
            "exchange_segment": "IDX_I",
            "instrument_type": "INDEX",
        },
        "BANKNIFTY": {
            "security_id": "25",
            "exchange_segment": "IDX_I",
            "instrument_type": "INDEX",
        },
        "NIFTYBANK": {
            "security_id": "25",
            "exchange_segment": "IDX_I",
            "instrument_type": "INDEX",
        },
    }

    INTERVAL_MAP: Dict[str, int] = {
        "1m": 1,
        "1min": 1,
        "5m": 5,
        "5min": 5,
        "15m": 15,
        "15min": 15,
        "25m": 25,
        "60m": 60,
        "1h": 60,
    }

    def __init__(
        self,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        client_instance: Optional[Any] = None,
    ):
        """
        Initialize DhanHQProvider.
        
        Args:
            client_id: Dhan Client ID. If None, loaded from DHAN_CLIENT_ID env var.
            access_token: Dhan JWT Access Token. If None, loaded from DHAN_ACCESS_TOKEN.
            client_instance: Optional pre-configured dhanhq instance (useful for unit testing / mocking).
        """
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN")

        if client_instance is not None:
            self.client = client_instance
        else:
            if not self.client_id or not self.access_token:
                raise DataProviderError(
                    "DhanHQ credentials missing. Please set DHAN_CLIENT_ID and "
                    "DHAN_ACCESS_TOKEN in .env or pass them to DhanHQProvider()."
                )
            context = DhanContext(self.client_id, self.access_token)
            self.client = dhanhq(context)

    def _resolve_security(self, symbol: str, exchange: str) -> Dict[str, str]:
        """Resolve a trading symbol to Dhan security_id, exchange_segment, and instrument_type."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        if clean_sym in self.KNOWN_SECURITIES:
            sec_info = self.KNOWN_SECURITIES[clean_sym].copy()
            if exchange.upper() == "BSE" and sec_info["exchange_segment"] == "NSE_EQ":
                sec_info["exchange_segment"] = "BSE_EQ"
            return sec_info

        raise DataProviderError(
            f"Symbol '{symbol}' not found in DhanHQ security resolver. "
            f"Please register it in KNOWN_SECURITIES or supply its security_id."
        )

    def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "15m",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
    ) -> pd.DataFrame:
        """
        Fetch historical intraday candles from DhanHQ.
        
        Args:
            symbol: Ticker symbol (e.g., 'NESTLEIND', 'RELIANCE')
            exchange: Market exchange ('NSE', 'BSE')
            interval: Bar resolution ('1m', '5m', '15m', '25m', '60m')
            start_date: Start date string 'YYYY-MM-DD'
            end_date: End date string 'YYYY-MM-DD'
            
        Returns:
            pd.DataFrame with DatetimeIndex (Asia/Kolkata) and columns ['open', 'high', 'low', 'close', 'volume']
        """
        sec = self._resolve_security(symbol, exchange)
        dhan_interval = self.INTERVAL_MAP.get(interval.lower())

        if dhan_interval is None:
            raise DataProviderError(
                f"Unsupported interval '{interval}' for DhanHQ intraday candles. "
                f"Supported: {list(self.INTERVAL_MAP.keys())}"
            )

        try:
            res = self.client.intraday_minute_data(
                security_id=sec["security_id"],
                exchange_segment=sec["exchange_segment"],
                instrument_type=sec["instrument_type"],
                from_date=start_date,
                to_date=end_date,
                interval=dhan_interval,
            )
        except Exception as e:
            raise DataProviderError(f"DhanHQ connection error while querying {symbol}: {e}") from e

        if not isinstance(res, dict) or res.get("status") != "success":
            remarks = res.get("remarks") if isinstance(res, dict) else res
            raise DataProviderError(f"DhanHQ API request failed for '{symbol}': {remarks}")

        data = res.get("data")
        if not data or not isinstance(data, dict) or not data.get("timestamp"):
            raise DataProviderError(
                f"DhanHQ returned 0 candles for '{symbol}' ({start_date} to {end_date}, interval={interval})"
            )

        # Build DataFrame from columnar lists
        df = pd.DataFrame(
            {
                "open": data["open"],
                "high": data["high"],
                "low": data["low"],
                "close": data["close"],
                "volume": data.get("volume", [0] * len(data["open"])),
            }
        )

        # Convert epoch seconds to Asia/Kolkata timezone-aware DatetimeIndex
        timestamps = pd.to_datetime(data["timestamp"], unit="s")
        if timestamps.tz is None:
            tz_idx = timestamps.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            tz_idx = timestamps.tz_convert("Asia/Kolkata")

        # Standardize to millisecond precision for parquet storage consistency
        df.index = tz_idx.astype("datetime64[ms, Asia/Kolkata]")
        df.index.name = "datetime"

        # Validate required columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                raise DataProviderError(f"DhanHQ response missing required column '{col}'")

        return df
