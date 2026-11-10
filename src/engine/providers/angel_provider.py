"""
Angel One SmartAPI Historical Market Data Provider.

Provides 100% free broker-grade historical intraday candles (10+ years depth)
using official SmartApi SDK and automated 2FA TOTP login.
"""

import os
import time
from typing import Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

import pyotp
from SmartApi import SmartConnect
from src.engine.data_feed import BaseDataProvider, DataProviderError


load_dotenv()


class AngelOneProvider(BaseDataProvider):
    """
    Historical market data provider connecting to Angel One SmartAPI.
    
    Supports:
    - 100% automated login using API Key, Client Code, PIN, and TOTP Secret
    - Free historical intraday candles (up to 200 days per 15m request)
    - Automated symbol to token resolution
    - Seamless caching to Parquet via DataFeed
    """

    KNOWN_TOKENS: Dict[str, Dict[str, str]] = {
        "NESTLEIND": {"token": "17963", "exchange": "NSE"},
        "RELIANCE": {"token": "2885", "exchange": "NSE"},
        "TCS": {"token": "11536", "exchange": "NSE"},
        "INFY": {"token": "1594", "exchange": "NSE"},
        "ALKEM": {"token": "11703", "exchange": "NSE"},
        "HDFCBANK": {"token": "1333", "exchange": "NSE"},
        "HINDUNILVR": {"token": "1394", "exchange": "NSE"},
        "NIFTY": {"token": "99926000", "exchange": "NSE"},
        "NIFTY50": {"token": "99926000", "exchange": "NSE"},
        "BANKNIFTY": {"token": "99926009", "exchange": "NSE"},
        "NIFTYBANK": {"token": "99926009", "exchange": "NSE"},
    }

    INTERVAL_MAP: Dict[str, str] = {
        "1m": "ONE_MINUTE",
        "1min": "ONE_MINUTE",
        "3m": "THREE_MINUTE",
        "5m": "FIVE_MINUTE",
        "5min": "FIVE_MINUTE",
        "10m": "TEN_MINUTE",
        "15m": "FIFTEEN_MINUTE",
        "15min": "FIFTEEN_MINUTE",
        "30m": "THIRTY_MINUTE",
        "60m": "ONE_HOUR",
        "1h": "ONE_HOUR",
        "1d": "ONE_DAY",
        "D": "ONE_DAY",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_code: Optional[str] = None,
        pin: Optional[str] = None,
        totp_secret: Optional[str] = None,
        smart_connect_instance: Optional[Any] = None,
    ):
        """
        Initialize AngelOneProvider.
        
        Args:
            api_key: SmartAPI App API Key. If None, loaded from ANGEL_API_KEY.
            client_code: Angel Client Code. If None, loaded from ANGEL_CLIENT_CODE.
            pin: Angel 4-digit PIN. If None, loaded from ANGEL_PIN.
            totp_secret: Google Authenticator TOTP Secret key. If None, loaded from ANGEL_TOTP_SECRET.
            smart_connect_instance: Optional pre-configured SmartConnect instance (for unit testing / mocking).
        """
        self.api_key = api_key or os.getenv("ANGEL_API_KEY")
        self.client_code = client_code or os.getenv("ANGEL_CLIENT_CODE")
        self.pin = pin or os.getenv("ANGEL_PIN")
        self.totp_secret = totp_secret or os.getenv("ANGEL_TOTP_SECRET")

        if smart_connect_instance is not None:
            self.client = smart_connect_instance
        else:
            if not all([self.api_key, self.client_code, self.pin, self.totp_secret]):
                raise DataProviderError(
                    "Angel One credentials missing. Please set ANGEL_API_KEY, "
                    "ANGEL_CLIENT_CODE, ANGEL_PIN, and ANGEL_TOTP_SECRET in .env"
                )
            self._login()

    def _login(self):
        """Perform automated session generation using TOTP."""
        try:
            totp = pyotp.TOTP(self.totp_secret).now()
            self.client = SmartConnect(api_key=self.api_key)
            login_data = self.client.generateSession(self.client_code, self.pin, totp)
            if not login_data or not login_data.get("status"):
                msg = login_data.get("message") if login_data else "Unknown error"
                raise DataProviderError(f"Angel One login failed: {msg}")
        except Exception as e:
            raise DataProviderError(f"Failed to authenticate with Angel One SmartAPI: {e}") from e

    def _resolve_token(self, symbol: str, exchange: str = "NSE") -> str:
        """Resolve symbol to Angel One numeric token."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        if clean_sym in self.KNOWN_TOKENS:
            return self.KNOWN_TOKENS[clean_sym]["token"]

        raise DataProviderError(
            f"Symbol '{symbol}' not found in Angel One token resolver. "
            f"Please register its numeric token in KNOWN_TOKENS."
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
        Fetch historical candles from Angel One SmartAPI.
        
        Args:
            symbol: Ticker symbol (e.g., 'NESTLEIND', 'RELIANCE')
            exchange: Market exchange ('NSE', 'BSE', 'NFO')
            interval: Bar resolution ('1m', '5m', '15m', '1h', '1d')
            start_date: Start date string 'YYYY-MM-DD'
            end_date: End date string 'YYYY-MM-DD'
            
        Returns:
            pd.DataFrame with DatetimeIndex (Asia/Kolkata) and lowercase ['open', 'high', 'low', 'close', 'volume']
        """
        token = self._resolve_token(symbol, exchange)
        angel_interval = self.INTERVAL_MAP.get(interval.lower())

        if not angel_interval:
            raise DataProviderError(
                f"Unsupported interval '{interval}' for Angel One. "
                f"Supported: {list(self.INTERVAL_MAP.keys())}"
            )

        # SmartAPI expects format 'YYYY-MM-DD HH:MM'
        from_str = f"{start_date} 09:15" if len(start_date) == 10 else start_date
        to_str = f"{end_date} 15:30" if len(end_date) == 10 else end_date

        params = {
            "exchange": exchange.upper(),
            "symboltoken": token,
            "interval": angel_interval,
            "fromdate": from_str,
            "todate": to_str,
        }

        max_retries = 6
        backoff_delays = [3.0, 6.0, 12.0, 20.0, 30.0, 45.0]
        res = None
        for attempt in range(max_retries):
            try:
                res = self.client.getCandleData(params)
                if isinstance(res, dict) and res.get("status"):
                    break
                msg = res.get("message") if isinstance(res, dict) else str(res)
                if "exceeding access rate" in msg.lower():
                    sleep_sec = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    print(f"⏳ [Rate Limit] Cooldown {sleep_sec}s (attempt {attempt + 1}/{max_retries})...", flush=True)
                    time.sleep(sleep_sec)
                    continue
                break
            except Exception as e:
                err_str = str(e).lower()
                if "exceeding access rate" in err_str or "expecting value" in err_str:
                    sleep_sec = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                    print(f"⏳ [Rate Limit] Cooldown {sleep_sec}s (attempt {attempt + 1}/{max_retries})...", flush=True)
                    time.sleep(sleep_sec)
                    if attempt == max_retries - 1:
                        raise DataProviderError(
                            f"Angel One rate limit exceeded for {symbol} after {max_retries} retries: {e}"
                        ) from e
                    continue
                raise DataProviderError(f"Angel One connection error while querying {symbol}: {e}") from e

        if not isinstance(res, dict) or not res.get("status"):
            msg = res.get("message") if isinstance(res, dict) else str(res)
            raise DataProviderError(f"Angel One getCandleData failed for '{symbol}': {msg}")

        candles = res.get("data")
        if not candles:
            raise DataProviderError(
                f"Angel One returned 0 candles for '{symbol}' ({start_date} to {end_date}, interval={interval})"
            )

        # SmartAPI returns list of rows: [timestamp_str, open, high, low, close, volume]
        records = []
        timestamps = []
        for row in candles:
            timestamps.append(row[0])
            records.append({
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": int(row[5]),
            })

        df = pd.DataFrame(records)
        dt_idx = pd.to_datetime(timestamps)
        if dt_idx.tz is None:
            df.index = dt_idx.tz_localize("Asia/Kolkata").astype("datetime64[ms, Asia/Kolkata]")
        else:
            df.index = dt_idx.tz_convert("Asia/Kolkata").astype("datetime64[ms, Asia/Kolkata]")

        df.index.name = "datetime"
        return df
