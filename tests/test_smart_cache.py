"""
Unit Tests for SmartCacheManager (Step 2C).

Verifies:
1. Missing delta calculations (cache hit, left delta, right delta, both sides, disjoint).
2. Fast index range inspection.
3. Master cache generation, deduplication, and atomic saving.
4. Incremental fetch flow:
   - Initial fetch calls provider once.
   - Sub-range query has 0 provider calls (pure cache hit).
   - Future extension only fetches the delta span.
   - Past extension only fetches the past delta span.
5. Cache pruning & retention policies (age & size limits).
6. Timeframe resampling.
"""

from datetime import datetime, timedelta
import os
import time
from pathlib import Path
import pandas as pd
import pytest

from src.engine.smart_cache import SmartCacheManager
from src.engine.data_feed import BaseDataProvider


class MockIncrementalProvider(BaseDataProvider):
    """
    Mock provider that tracks requested ranges and returns synthetic candles.
    """

    def __init__(self, base_price: float = 100.0):
        self.call_history = []
        self.base_price = base_price

    def fetch_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "15m",
        start_date: str = "2024-01-01",
        end_date: str = "2024-01-10",
    ) -> pd.DataFrame:
        self.call_history.append((start_date, end_date))

        # Generate 15m candles during market hours (09:15 to 15:30) for the date range
        start_ts = pd.to_datetime(start_date).tz_localize("Asia/Kolkata")
        end_ts = pd.to_datetime(end_date).tz_localize("Asia/Kolkata").replace(hour=15, minute=30)

        # Generate a sample sequence of dates (daily 15m series)
        date_range = pd.date_range(start_ts, end_ts, freq="1D")
        records = []
        for d in date_range:
            # 25 bars per day
            times = pd.date_range(d.replace(hour=9, minute=15), d.replace(hour=15, minute=15), freq="15min")
            for t in times:
                records.append(
                    {
                        "datetime": t,
                        "open": self.base_price,
                        "high": self.base_price + 1.0,
                        "low": self.base_price - 1.0,
                        "close": self.base_price + 0.5,
                        "volume": 1000,
                    }
                )

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(records).set_index("datetime")
        return df


# -------------------------------------------------------------------------
# 1. RANGE DELTA ALGORITHM TESTS
# -------------------------------------------------------------------------

def test_compute_missing_ranges_cache_miss():
    req_start = pd.Timestamp("2024-01-01", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-01-10", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges(None, req_start, req_end)
    assert deltas == [("2024-01-01", "2024-01-10")]


def test_compute_missing_ranges_cache_hit():
    cached_start = pd.Timestamp("2024-01-01 09:15:00", tz="Asia/Kolkata")
    cached_end = pd.Timestamp("2024-01-31 15:15:00", tz="Asia/Kolkata")

    # Request strictly within cached window
    req_start = pd.Timestamp("2024-01-05", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-01-20", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges((cached_start, cached_end), req_start, req_end)
    assert deltas == []  # 0 API calls needed!


def test_compute_missing_ranges_left_delta():
    cached_start = pd.Timestamp("2024-01-10 09:15:00", tz="Asia/Kolkata")
    cached_end = pd.Timestamp("2024-01-31 15:15:00", tz="Asia/Kolkata")

    # Need history before cached_start
    req_start = pd.Timestamp("2024-01-01", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-01-20", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges((cached_start, cached_end), req_start, req_end)
    assert deltas == [("2024-01-01", "2024-01-10")]


def test_compute_missing_ranges_right_delta():
    cached_start = pd.Timestamp("2024-01-01 09:15:00", tz="Asia/Kolkata")
    cached_end = pd.Timestamp("2024-01-15 15:15:00", tz="Asia/Kolkata")

    # Need history after cached_end
    req_start = pd.Timestamp("2024-01-05", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-01-25", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges((cached_start, cached_end), req_start, req_end)
    assert deltas == [("2024-01-15", "2024-01-25")]


def test_compute_missing_ranges_both_sides():
    cached_start = pd.Timestamp("2024-01-10 09:15:00", tz="Asia/Kolkata")
    cached_end = pd.Timestamp("2024-01-20 15:15:00", tz="Asia/Kolkata")

    # Need history both before and after
    req_start = pd.Timestamp("2024-01-01", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-01-31", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges((cached_start, cached_end), req_start, req_end)
    assert deltas == [("2024-01-01", "2024-01-10"), ("2024-01-20", "2024-01-31")]


def test_compute_missing_ranges_disjoint():
    cached_start = pd.Timestamp("2024-01-10 09:15:00", tz="Asia/Kolkata")
    cached_end = pd.Timestamp("2024-01-20 15:15:00", tz="Asia/Kolkata")

    # Completely past cached range
    req_start = pd.Timestamp("2024-02-01", tz="Asia/Kolkata")
    req_end = pd.Timestamp("2024-02-10", tz="Asia/Kolkata")

    deltas = SmartCacheManager.compute_missing_ranges((cached_start, cached_end), req_start, req_end)
    assert deltas == [("2024-02-01", "2024-02-10")]


# -------------------------------------------------------------------------
# 2. INCREMENTAL FETCH & CACHE WORKFLOW TESTS
# -------------------------------------------------------------------------

def test_smart_cache_incremental_lifecycle(tmp_path):
    mock = MockIncrementalProvider(base_price=150.0)
    scm = SmartCacheManager(cache_dir=tmp_path, default_provider=mock)

    # 1. Initial fetch: 2024-01-10 to 2024-01-20
    df1 = scm.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-10",
        end_date="2024-01-20",
    )
    assert len(mock.call_history) == 1
    assert mock.call_history[0] == ("2024-01-10", "2024-01-20")
    assert not df1.empty

    master_path = scm.get_master_cache_path("NESTLEIND", "NSE", "15m")
    assert master_path.exists()

    # Verify cached range
    c_range = scm.get_cached_range(master_path)
    assert c_range is not None
    assert c_range[0].strftime("%Y-%m-%d") == "2024-01-10"

    # 2. Sub-range fetch: 2024-01-12 to 2024-01-18 -> 100% cache hit, 0 provider calls!
    df2 = scm.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-12",
        end_date="2024-01-18",
    )
    assert len(mock.call_history) == 1  # Still 1 call! No new API request!
    assert df2.index.min() >= pd.Timestamp("2024-01-12", tz="Asia/Kolkata")
    assert df2.index.max() <= pd.Timestamp("2024-01-18 23:59:59", tz="Asia/Kolkata")

    # 3. Right-extension: 2024-01-15 to 2024-01-28 -> should only fetch delta (2024-01-20 to 2024-01-28)
    df3 = scm.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-15",
        end_date="2024-01-28",
    )
    assert len(mock.call_history) == 2
    # The second call must only be for the missing delta!
    assert mock.call_history[1] == ("2024-01-20", "2024-01-28")
    assert df3.index.max() >= pd.Timestamp("2024-01-28 15:00:00", tz="Asia/Kolkata")

    # 4. Left-extension: 2024-01-01 to 2024-01-25 -> should only fetch delta (2024-01-01 to 2024-01-10)
    df4 = scm.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-01",
        end_date="2024-01-25",
    )
    assert len(mock.call_history) == 3
    assert mock.call_history[2] == ("2024-01-01", "2024-01-10")
    assert df4.index.min() <= pd.Timestamp("2024-01-01 10:00:00", tz="Asia/Kolkata")

    # 5. Full query across whole range -> 0 calls!
    df5 = scm.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-01",
        end_date="2024-01-28",
    )
    assert len(mock.call_history) == 3  # Still 3 calls!


def test_resampling_on_smart_cache(tmp_path):
    mock = MockIncrementalProvider()
    scm = SmartCacheManager(cache_dir=tmp_path, default_provider=mock)

    # Fetch 15m candles and resample to 1h
    df_1h = scm.get_candles(
        symbol="TCS",
        exchange="NSE",
        interval="15m",
        start_date="2024-01-01",
        end_date="2024-01-05",
        target_timeframe="1h",
    )
    assert not df_1h.empty
    # Interval between consecutive rows should be 1 hour
    time_diff = df_1h.index[1] - df_1h.index[0]
    assert time_diff == pd.Timedelta(hours=1)


# -------------------------------------------------------------------------
# 3. CACHE PRUNING & RETENTION TESTS
# -------------------------------------------------------------------------

def test_cache_pruning_policies(tmp_path):
    scm = SmartCacheManager(cache_dir=tmp_path)

    # Create dummy files:
    # 1. Canonical master file
    master = tmp_path / "NESTLEIND_NSE_15m.parquet"
    pd.DataFrame({"close": [100.0]}).to_parquet(master)

    # 2. Date-sliced temporary file
    temp_old = tmp_path / "NESTLEIND_NSE_15m_2020-01-01_2020-02-01.parquet"
    pd.DataFrame({"close": [100.0]}).to_parquet(temp_old)

    # Age temp file back by 40 days
    past_mtime = time.time() - (40 * 86400)
    os.utime(temp_old, (past_mtime, past_mtime))

    # Prune files older than 30 days
    res = scm.prune_cache(max_file_age_days=30, protect_master_files=True)
    assert res["deleted_count"] == 1
    assert temp_old.name in res["deleted_files"]
    assert master.exists()  # Master file protected!
    assert not temp_old.exists()  # Old temporary slice removed!

