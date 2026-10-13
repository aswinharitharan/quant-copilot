from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import pandas as pd


class DataProviderError(Exception):
    """Exception raised for errors during market data retrieval."""
    pass


class BaseDataProvider(ABC):
    """
    Abstract Base Class for historical market data providers.
    
    Any concrete provider (e.g., YFinanceProvider, DhanHQProvider) must
    implement fetch_candles and return a pandas DataFrame adhering to
    the standard OHLCV schema:
      - Index: DatetimeIndex (timezone-aware IST preferred)
      - Columns: 'open', 'high', 'low', 'close', 'volume' (all float/numeric)
    """

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candle data.
        
        Args:
            symbol: Ticker symbol (e.g., 'NESTLEIND', 'NIFTY')
            exchange: Market exchange ('NSE', 'BSE', 'MCX')
            interval: Bar resolution ('1m', '5m', '15m', '1d')
            start_date: Start date string 'YYYY-MM-DD'
            end_date: End date string 'YYYY-MM-DD'
            
        Returns:
            pd.DataFrame with DatetimeIndex and lowercase ['open', 'high', 'low', 'close', 'volume']
        """
        pass


class DataFeed:
    """
    Deterministic Market Data Feed & Cache Manager.
    
    Responsibilities:
    1. Query local Parquet cache first (zero-network replay).
    2. Delegate cache misses to the configured BaseDataProvider.
    3. Persist fetched candles to compressed Parquet format.
    4. Resample raw candles (e.g., 1m raw -> 15m target) deterministically.
    """

    TIMEFRAME_MAP = {
        "1m": "1min",
        "3m": "3min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "1d": "1D",
        "D": "1D",
    }

    REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]

    def __init__(
        self,
        provider: BaseDataProvider,
        cache_dir: Optional[str] = "./data/cache",
    ):
        """
        Args:
            provider: Concrete BaseDataProvider instance.
            cache_dir: Path to directory where .parquet caches are stored.
        """
        self.provider = provider
        self.cache_dir = Path(cache_dir) if cache_dir else Path("./data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _build_cache_key(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> str:
        """Create a deterministic filename for the cache entry."""
        safe_symbol = symbol.replace("/", "_").replace(":", "_").replace("^", "")
        return f"{safe_symbol}_{exchange}_{interval}_{start_date}_{end_date}.parquet"

    def get_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
        target_timeframe: Optional[str] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Retrieve historical candles.
        
        Checks Parquet cache first. If absent or force_refresh=True, fetches
        from the provider, saves to cache, and returns. If target_timeframe
        is provided and differs from interval, resamples before returning.
        """
        cache_key = self._build_cache_key(symbol, exchange, interval, start_date, end_date)
        cache_file = self.cache_dir / cache_key

        if cache_file.exists() and not force_refresh:
            df = pd.read_parquet(cache_file)
        else:
            df = self.provider.fetch_candles(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )
            df = self._normalize_dataframe(df)
            df.to_parquet(cache_file, engine="pyarrow")

        # Timeframe resampling if requested
        if target_timeframe and target_timeframe != interval:
            df = self.resample_candles(df, target_timeframe)

        return df

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard lowercase column names and types."""
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                raise DataProviderError(f"Missing required candle column: '{col}'")

        # Filter strictly to the required OHLCV columns (preserve any existing extra columns at end)
        cols_order = self.REQUIRED_COLUMNS + [c for c in df.columns if c not in self.REQUIRED_COLUMNS]
        df = df[cols_order]

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = "datetime"

        return df

    @classmethod
    def resample_candles(cls, df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        """
        Resample raw OHLCV candles to a target timeframe.
        
        Aggregation rules:
          - open: first
          - high: max
          - low: min
          - close: last
          - volume: sum
        
        Empty/non-trading periods are automatically dropped.
        """
        if df.empty:
            return df.copy()

        rule = cls.TIMEFRAME_MAP.get(target_timeframe, target_timeframe)

        resampled = df.resample(rule).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )

        # Drop intervals with zero trading activity (e.g. non-market hours)
        resampled = resampled.dropna(subset=["open"])
        resampled.index.name = "datetime"
        return resampled
