"""Yahoo Finance Data Provider Module.

Provides offline and development market data access by wrapping the yfinance
library, mapping Indian exchange symbols (NSE/BSE/Indices) to Yahoo Finance
ticker format, and executing resilient candle downloads with exponential back-off retries.
"""

import logging
import time
from typing import Dict, Optional
import pandas as pd
import yfinance as yf

from src.engine.data_feed import BaseDataProvider, DataProviderError

logger = logging.getLogger(__name__)


class YFinanceProvider(BaseDataProvider):
    """
    Offline/development data provider using Yahoo Finance (yfinance).
    
    Translates NSE symbols to Yahoo Finance format:
      - Equities: 'NESTLEIND' -> 'NESTLEIND.NS'
      - Indices: 'NIFTY' -> '^NSEI', 'BANKNIFTY' -> '^NSEBANK'
    """

    INDEX_MAP: Dict[str, str] = {
        "NIFTY": "^NSEI",
        "NIFTY50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "NIFTYBANK": "^NSEBANK",
    }

    INTERVAL_MAP: Dict[str, str] = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "60m",
        "1d": "1d",
        "D": "1d",
    }

    def _resolve_ticker(self, symbol: str, exchange: str) -> str:
        """Map symbol to Yahoo Finance ticker format."""
        clean = symbol.upper().strip()
        if clean in self.INDEX_MAP:
            return self.INDEX_MAP[clean]

        if clean.startswith("^") or clean.endswith(".NS") or clean.endswith(".BO"):
            return clean

        if exchange.upper() == "BSE":
            return f"{clean}.BO"

        # Default to NSE
        return f"{clean}.NS"

    def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
    ) -> pd.DataFrame:
        """Fetch historical candles via yfinance with retry loop and exponential back-off."""
        yf_ticker = self._resolve_ticker(symbol, exchange)
        yf_interval = self.INTERVAL_MAP.get(interval, interval)

        # yfinance treats `end` as exclusive, so add 1 calendar day to make `end_date` inclusive
        try:
            yf_end = (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            yf_end = end_date

        df = None
        last_err = None
        for attempt in range(3):
            try:
                ticker = yf.Ticker(yf_ticker)
                df = ticker.history(start=start_date, end=yf_end, interval=yf_interval)
                if df is not None and not df.empty:
                    break
            except Exception as e:
                last_err = e
                logger.warning(
                    "Attempt %d/3 failed to fetch data from yfinance for '%s': %s",
                    attempt + 1,
                    yf_ticker,
                    e,
                )
                time.sleep(0.5 * (2 ** attempt))

        if df is None or df.empty:
            if last_err:
                raise DataProviderError(f"Failed to fetch data from yfinance for '{yf_ticker}': {last_err}") from last_err
            raise DataProviderError(
                f"yfinance returned 0 candles for '{yf_ticker}' ({start_date} to {end_date}, interval={yf_interval})"
            )

        # Normalize column names to lowercase
        df.columns = [str(c).lower() for c in df.columns]

        # Ensure required OHLCV columns exist
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise DataProviderError(f"yfinance data missing required column: '{col}'")

        df = df[required]

        # Ensure timezone is Asia/Kolkata
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        df.index.name = "datetime"
        return df
