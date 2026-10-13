from typing import Dict, Optional
import pandas as pd
import yfinance as yf

from src.engine.data_feed import BaseDataProvider, DataProviderError


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
        """Fetch historical candles via yfinance."""
        yf_ticker = self._resolve_ticker(symbol, exchange)
        yf_interval = self.INTERVAL_MAP.get(interval, interval)

        try:
            ticker = yf.Ticker(yf_ticker)
            df = ticker.history(start=start_date, end=end_date, interval=yf_interval)
        except Exception as e:
            raise DataProviderError(f"Failed to fetch data from yfinance for '{yf_ticker}': {e}") from e

        if df.empty:
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
