"""
Smart Incremental Master Cache Manager.

Provides range-aware caching for historical candle data:
- Manages single self-contained master Parquet files per symbol/exchange/interval.
- Inspects covered time ranges in <2ms using PyArrow without loading full datasets.
- Automatically computes missing time deltas (prepend/append/fill) and only fetches
  uncovered date spans from market data providers.
- Deduplicates and merges new candles atomically with concurrency protection.
- Supports provider injection at runtime (Angel One SmartAPI default, Dhan, YFinance, etc.).
- Includes cache retention and pruning policies.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd

from src.engine.data_feed import BaseDataProvider, DataFeed, DataProviderError


class SmartCacheManager:
    """
    Range-aware smart cache manager with incremental delta fetching.
    """

    REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]

    def __init__(
        self,
        cache_dir: Union[str, Path] = "./data/cache",
        default_provider: Optional[Union[str, BaseDataProvider]] = "angel",
    ):
        """
        Args:
            cache_dir: Directory where master .parquet files are stored.
            default_provider: 'angel', 'dhan', 'yfinance', or a concrete BaseDataProvider instance.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._default_provider_spec = default_provider
        self._provider_cache: Dict[str, BaseDataProvider] = {}

    # -------------------------------------------------------------------------
    # 1. FILE LOCKING & ATOMIC STORAGE
    # -------------------------------------------------------------------------

    @contextmanager
    def _file_lock(self, lock_path: Path):
        """Cross-process file lock using standard library fcntl (POSIX/macOS/Linux)."""
        lock_file = lock_path.with_suffix(lock_path.suffix + ".lock")
        f = open(lock_file, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()
            try:
                if lock_file.exists():
                    lock_file.unlink()
            except OSError:
                pass

    def get_master_cache_path(
        self, symbol: str, exchange: str = "NSE", interval: str = "15m"
    ) -> Path:
        """Return the canonical master parquet path for an instrument.
        
        Normalizes symbol (upper & stripped) before building cache key.
        """
        clean_symbol = symbol.upper().strip().replace("/", "_").replace(":", "_").replace("^", "")
        clean_exchange = exchange.upper().strip()
        clean_interval = interval.strip()
        return self.cache_dir / f"{clean_symbol}_{clean_exchange}_{clean_interval}.parquet"

    # -------------------------------------------------------------------------
    # 2. FAST RANGE INSPECTION
    # -------------------------------------------------------------------------

    def get_cached_range(
        self, file_path: Path
    ) -> Optional[Tuple[pd.Timestamp, pd.Timestamp]]:
        """
        Inspect the minimum and maximum timestamps in the parquet file
        without reading the full dataset into memory.
        
        Returns:
            Tuple of (min_timestamp, max_timestamp) or None if file doesn't exist or is empty.
        """
        if not file_path.is_file():
            return None

        try:
            # Read index column only - lightning fast in PyArrow
            idx_df = pd.read_parquet(file_path, columns=[])
            if len(idx_df.index) == 0 or not isinstance(idx_df.index, pd.DatetimeIndex):
                return None
            return (idx_df.index.min(), idx_df.index.max())
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # 3. RANGE DELTA COMPUTATION
    # -------------------------------------------------------------------------

    @staticmethod
    def compute_missing_ranges(
        cached_range: Optional[Tuple[pd.Timestamp, pd.Timestamp]],
        req_start: pd.Timestamp,
        req_end: pd.Timestamp,
    ) -> List[Tuple[str, str]]:
        """
        Calculate date intervals (in 'YYYY-MM-DD' format) that must be fetched
        from the market data provider.
        
        Args:
            cached_range: (min_ts, max_ts) from the cache, or None if no cache.
            req_start: requested start timestamp (timezone-aware).
            req_end: requested end timestamp (timezone-aware).
            
        Returns:
            List of (start_date_str, end_date_str) tuples to fetch.
        """
        if cached_range is None:
            # Complete cache miss: fetch entire range
            return [(req_start.strftime("%Y-%m-%d"), req_end.strftime("%Y-%m-%d"))]

        c_start, c_end = cached_range
        # Normalize timezones if needed
        if req_start.tz is not None and c_start.tz is None:
            c_start = c_start.tz_localize(req_start.tz)
            c_end = c_end.tz_localize(req_start.tz)
        elif req_start.tz is None and c_start.tz is not None:
            req_start = req_start.tz_localize(c_start.tz)
            req_end = req_end.tz_localize(c_start.tz)

        req_start_date = req_start.date()
        req_end_date = req_end.date()
        c_start_date = c_start.date()
        c_end_date = c_end.date()

        # Case 1: Entirely disjoint (requested entirely before or after cached range)
        if req_end_date < c_start_date or req_start_date > c_end_date:
            return [(req_start.strftime("%Y-%m-%d"), req_end.strftime("%Y-%m-%d"))]

        missing: List[Tuple[str, str]] = []

        # Case 2: Need left delta (calendar dates strictly before cached start date)
        if req_start_date < c_start_date:
            missing.append(
                (req_start.strftime("%Y-%m-%d"), c_start.strftime("%Y-%m-%d"))
            )

        # Case 3: Need right delta (calendar dates strictly after cached end date,
        # or same date if cached end was partial intraday session before 15:30)
        needs_right = False
        if req_end_date > c_end_date:
            needs_right = True
        elif req_end_date == c_end_date and c_end.hour < 15 and req_end.hour >= 15:
            # Partial cached intraday day needs remainder
            needs_right = True

        if needs_right:
            missing.append(
                (c_end.strftime("%Y-%m-%d"), req_end.strftime("%Y-%m-%d"))
            )

        return missing

    # -------------------------------------------------------------------------
    # 4. PROVIDER RESOLUTION
    # -------------------------------------------------------------------------

    def resolve_provider(
        self, provider_spec: Optional[Union[str, BaseDataProvider]] = None
    ) -> BaseDataProvider:
        """
        Resolve provider instance from string name or object.
        Supports lazy instantiation so credentials aren't checked until needed.
        """
        spec = provider_spec or self._default_provider_spec

        if isinstance(spec, BaseDataProvider):
            return spec

        spec_str = str(spec).lower().strip()
        if spec_str in self._provider_cache:
            return self._provider_cache[spec_str]

        if spec_str in ("angel", "angelone", "smartapi"):
            from src.engine.providers.angel_provider import AngelOneProvider
            provider = AngelOneProvider()
        elif spec_str in ("dhan", "dhanhq"):
            from src.engine.providers.dhan_provider import DhanProvider
            provider = DhanProvider()
        elif spec_str in ("yfinance", "yahoo"):
            from src.engine.providers.yfinance_provider import YFinanceProvider
            provider = YFinanceProvider()
        else:
            raise ValueError(f"Unknown market data provider: '{spec}'. Must be 'angel', 'dhan', or 'yfinance'.")

        self._provider_cache[spec_str] = provider
        return provider

    # -------------------------------------------------------------------------
    # 5. ATOMIC MERGE & PARQUET WRITE
    # -------------------------------------------------------------------------

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard lowercase column names, required OHLCV schema, and datetime index."""
        if df.empty:
            return df.copy()

        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        for col in self.REQUIRED_COLUMNS:
            if col not in df.columns:
                raise DataProviderError(f"Missing required candle column: '{col}'")

        # Standardize index to datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = "datetime"

        # Ensure timezone IST if tz-naive
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        # Sort and deduplicate by index
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df

    def merge_and_save(self, master_path: Path, new_df: pd.DataFrame) -> pd.DataFrame:
        """
        Merge new data with existing Parquet cache file atomically with file locking.
        
        Returns:
            The combined, sorted, and deduplicated DataFrame.
        """
        new_norm = self._normalize_dataframe(new_df)
        if new_norm.empty:
            if master_path.exists():
                return pd.read_parquet(master_path)
            return new_norm

        with self._file_lock(master_path):
            if master_path.is_file():
                try:
                    existing_df = pd.read_parquet(master_path)
                    existing_norm = self._normalize_dataframe(existing_df)
                    combined = pd.concat([existing_norm, new_norm])
                except Exception:
                    # In case of corrupted file, overwrite with new valid data
                    combined = new_norm
            else:
                combined = new_norm

            combined = combined[~combined.index.duplicated(keep="last")].sort_index()

            # Atomic write via temporary file
            temp_path = master_path.with_suffix(f".tmp_{os.getpid()}_{time.time_ns()}.parquet")
            combined.to_parquet(temp_path, engine="pyarrow", compression="snappy")
            os.replace(temp_path, master_path)

        return combined

    # -------------------------------------------------------------------------
    # 6. PUBLIC API: GET CANDLES (INCREMENTAL)
    # -------------------------------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "15m",
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
        target_timeframe: Optional[str] = None,
        provider: Optional[Union[str, BaseDataProvider]] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Retrieve historical candles using smart incremental caching.
        
        1. Checks existing master cache coverage in milliseconds.
        2. If requested range is already covered -> 0 API calls, instant load.
        3. If missing delta ranges exist -> fetches ONLY missing spans from provider.
        4. Merges, deduplicates, and saves back to master cache.
        5. Returns the exact requested slice.
        """
        master_path = self.get_master_cache_path(symbol, exchange, interval)

        # Parse requested range to timezone-aware timestamps (Asia/Kolkata)
        req_start = pd.to_datetime(start_date)
        req_end = pd.to_datetime(end_date)
        if req_start.tz is None:
            req_start = req_start.tz_localize("Asia/Kolkata")
        if req_end.tz is None:
            req_end = req_end.tz_localize("Asia/Kolkata")
        # Ensure req_end covers full end date (23:59:59) if only date provided
        if req_end.hour == 0 and req_end.minute == 0 and req_end.second == 0:
            req_end = req_end.replace(hour=23, minute=59, second=59)

        cached_range = None if force_refresh else self.get_cached_range(master_path)
        missing_deltas = self.compute_missing_ranges(cached_range, req_start, req_end)

        if missing_deltas:
            prov = self.resolve_provider(provider)
            fetched_dfs: List[pd.DataFrame] = []

            for delta_start, delta_end in missing_deltas:
                try:
                    df_gap = prov.fetch_candles(
                        symbol=symbol,
                        exchange=exchange,
                        interval=interval,
                        start_date=delta_start,
                        end_date=delta_end,
                    )
                    if not df_gap.empty:
                        fetched_dfs.append(df_gap)
                except DataProviderError as e:
                    # If this was an incremental delta on top of an existing master cache and
                    # the delta range had 0 candles (e.g., weekend or market holiday), do not crash.
                    if master_path.exists() and "0 candles" in str(e):
                        continue
                    raise

            if fetched_dfs:
                combined_new = pd.concat(fetched_dfs)
                full_df = self.merge_and_save(master_path, combined_new)
            elif master_path.exists():
                full_df = pd.read_parquet(master_path)
            else:
                full_df = pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        else:
            # 100% Cache hit! 0 API calls
            full_df = pd.read_parquet(master_path)

        # Standardize full dataframe
        full_df = self._normalize_dataframe(full_df)

        if full_df.empty:
            return full_df

        # Slice to requested range
        sliced = full_df.loc[(full_df.index >= req_start) & (full_df.index <= req_end)].copy()

        # Resample if target timeframe requested
        if target_timeframe and target_timeframe != interval:
            sliced = DataFeed.resample_candles(sliced, target_timeframe)

        return sliced

    # -------------------------------------------------------------------------
    # 7. CACHE RETENTION & PRUNING
    # -------------------------------------------------------------------------

    def prune_cache(
        self,
        max_file_age_days: Optional[int] = None,
        max_total_size_mb: Optional[int] = None,
        protect_master_files: bool = True,
    ) -> Dict[str, Any]:
        """
        Prunes cache files based on age or size budget.
        
        Args:
            max_file_age_days: Remove files not modified in X days.
            max_total_size_mb: Max allowable total size in MB for the cache directory.
            protect_master_files: If True, only prunes date-sliced or temporary files,
                                  preserving canonical master `{symbol}_{exchange}_{interval}.parquet`.
                                  
        Returns:
            Dict containing count of deleted files and total bytes freed.
        """
        now = time.time()
        files = list(self.cache_dir.glob("*.parquet"))
        deleted_files: List[str] = []
        bytes_freed = 0

        # Age-based pruning
        if max_file_age_days is not None:
            max_age_sec = max_file_age_days * 86400
            for f in files:
                # Check protection
                parts = f.stem.split("_")
                is_master = len(parts) == 3  # symbol_exchange_interval
                if protect_master_files and is_master:
                    continue

                mtime = f.stat().st_mtime
                if (now - mtime) > max_age_sec:
                    size = f.stat().st_size
                    f.unlink(missing_ok=True)
                    deleted_files.append(f.name)
                    bytes_freed += size

        # Size-based pruning (removes oldest files first)
        if max_total_size_mb is not None:
            max_bytes = max_total_size_mb * 1024 * 1024
            remaining_files = sorted(
                [f for f in self.cache_dir.glob("*.parquet") if f.name not in deleted_files],
                key=lambda x: x.stat().st_mtime,
            )
            total_size = sum(f.stat().st_size for f in remaining_files)

            for f in remaining_files:
                if total_size <= max_bytes:
                    break
                parts = f.stem.split("_")
                is_master = len(parts) == 3
                if protect_master_files and is_master:
                    continue

                size = f.stat().st_size
                f.unlink(missing_ok=True)
                deleted_files.append(f.name)
                bytes_freed += size
                total_size -= size

        return {
            "deleted_count": len(deleted_files),
            "bytes_freed": bytes_freed,
            "deleted_files": deleted_files,
        }
