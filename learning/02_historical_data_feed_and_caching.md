# Lesson 2: Historical Data Feed & Smart Incremental Master Cache

**Modules:** `src/engine/data_feed.py`, `src/engine/smart_cache.py`, `src/engine/expiry_calendar.py`, `src/engine/providers/angel_provider.py`

In quantitative finance, the quality and speed of your backtest are entirely dictated by how you ingest, store, and process market data. In this lesson, we explore how QuantCopilot solves market data feeding, local caching, range-aware incremental delta fetching, and Indian exchange calendar mechanics.

---

## 1. WHAT is the Data Feed Engine?

The Data Feed acts as the **fuel line** for the backtester:
* When a strategy requests: *"Give me 15-minute candles for NESTLEIND from 2024-01-01 to 2024-12-31"*, the Data Feed delivers clean, timezone-standardized (IST) OHLCV data.
* It operates on a **Cache-First principle**:
  1. Check local disk for a pre-saved `.parquet` file.
  2. If found, load it in ~10 milliseconds (zero network calls, zero rate-limiting).
  3. If missing, fetch from the data provider, save it to disk, and return it.

---

## 2. The Evolution to Smart Incremental Master Caching (`SmartCacheManager`)

### The Problem with Static Date-Keyed Caching
Originally, cache files were saved with exact date-window strings:
`NESTLEIND_NSE_15m_2024-01-01_2024-06-30.parquet`

If the user then requested `2024-01-01` to `2024-12-31`, a naive cache system treated this as a complete cache miss, re-downloading the entire year—wasting broker API rate limits and bandwidth.

### The Solution: Range-Aware Incremental Fetching
`SmartCacheManager` (`src/engine/smart_cache.py`) upgrades the storage to a **single canonical Master Parquet file** per instrument and timeframe:
`data/cache/NESTLEIND_NSE_15m.parquet`

#### How It Operates in Milliseconds:
1. **Sub-2ms Time Range Inspection (PyArrow)**:
   Instead of reading millions of rows into RAM, `pd.read_parquet(master_path, columns=[])` reads only the index metadata from the file footer. It retrieves the exact `(min_timestamp, max_timestamp)` in less than 2 milliseconds.
2. **Delta Interval Calculation (`compute_missing_ranges`)**:
   - **Full Cache Hit**: If requested range is inside cached range $\rightarrow$ **0 API calls**, instantaneous slice returned.
   - **Left Delta (Prepend)**: If requesting older history $\rightarrow$ queries only the missing dates prior to cached start.
   - **Right Delta (Append)**: If requesting newer history $\rightarrow$ queries only the missing dates after cached end.
   - **Disjoint / Miss**: If no cache exists $\rightarrow$ queries the full window.
3. **Atomic Merge & Concurrency Protection**:
   When new delta candles arrive, they are concatenated with existing data, deduplicated by timestamp (`~combined.index.duplicated(keep="last")`), sorted, and atomically written via temporary file swap (`os.replace`) guarded by a cross-process lock (`fcntl.flock`).
4. **Runtime Provider Selection**:
   Defaults to Angel One SmartAPI for 10+ years of free historical depth, but seamlessly accepts DhanHQ, YFinance, or custom instances at runtime.
5. **Cache Retention & Pruning (`prune_cache`)**:
   Allows cleaning stale temporary slices by age (e.g., >30 days) or enforcing a maximum directory size budget while keeping master parquet files protected.

---

## 3. WHY an Abstract Base Class (`BaseDataProvider(ABC)`)?

In algorithmic trading, data sources change constantly:
* During offline prototyping, you want **free data** without API keys (`YFinanceProvider`).
* In production, you want **official 1-minute broker tick data** (`DhanHQProvider`).
* For deep 10+ year historical intraday archives with automated TOTP 2FA, you use **Angel One SmartAPI** (`AngelOneProvider`).

### The Design Pattern: Dependency Inversion
If we hardcoded Yahoo Finance inside our backtester, switching to DhanHQ or Angel One would require rewriting the backtester!

By defining an **Abstract Base Class (`BaseDataProvider`)**, we create a rigid contract:
```python
class BaseDataProvider(ABC):
    @abstractmethod
    def fetch_candles(self, symbol, exchange, interval, start_date, end_date) -> pd.DataFrame:
        pass
```

`DataFeed` and `SmartCacheManager` only interact with `BaseDataProvider`. To swap providers, you change **exactly 1 line of configuration**:
```python
# Default Angel One SmartAPI (10+ year free history):
cache = SmartCacheManager(default_provider="angel")

# Or switch to DhanHQ or YFinance at runtime:
df = cache.get_candles("NESTLEIND", "NSE", "15m", "2024-01-01", "2024-12-31", provider="dhan")
```
The caching, deduplication, timeframe resampling, and backtesting math never change by a single line of code.

---

## 4. WHY Apache Parquet instead of Plain CSV?

In high-frequency and quant backtesting, storing 1-minute intraday data in CSV is an anti-pattern:

| Dimension | Plain CSV (`.csv`) | Apache Parquet (`.parquet`) |
| :--- | :--- | :--- |
| **Format** | Text lines separated by commas | Columnar binary compressed (Snappy) |
| **Data Types** | Everything is a string. Datetimes require slow parsing (`pd.to_datetime`). | Strict native types (int64, float64, IST DatetimeIndex). Zero parsing needed. |
| **File Size** | Bulky (tens of megabytes). | **75% to 90% smaller** (compresses identical column values). |
| **Read Speed** | Seconds per file (disk bottleneck). | **~5 to 15 milliseconds** directly into memory via `pyarrow`. |

Because `.parquet` files are **ephemeral caches** generated automatically on demand, we exclude them from Git (`data/` in `.gitignore`) to keep the repository lightweight.

---

## 4. HOW does Timeframe Resampling Work?

Indian market strategies frequently operate on 5-minute, 15-minute, or 1-hour candles. Rather than requiring separate downloads for every timeframe, `DataFeed.resample_candles()` aggregates raw lower-timeframe bars using strict market rules:

* **Open**: The `open` price of the **first** minute in the interval.
* **High**: The **highest** price reached across all minutes in the interval.
* **Low**: The **lowest** price reached across all minutes in the interval.
* **Close**: The `close` price of the **last** minute in the interval.
* **Volume**: The **sum** of all volume traded during the interval.

```python
resampled = df.resample(rule).agg({
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum"
}).dropna(subset=["open"])
```
Intervals where the exchange was closed (e.g. overnight or weekends) contain no trades and are automatically pruned.

---

## 5. The NSE Expiry Calendar & Days-to-Expiry (DTE)

For derivative strategies (like our [Nestle India 200 SMA Benchmark](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/BENCHMARK_STRATEGY_NESTLEIND_200SMA.md)), contract expiration is a critical boundary:

1. **The Last Thursday Rule**: NSE stock futures expire on the last Thursday of each month.
2. **The Holiday Shift Rule**: If that Thursday is an NSE trading holiday (e.g., Diwali, Good Friday, Eid), the expiry **automatically shifts to the previous trading day** (usually Wednesday).

### Why DTE Matters
Our benchmark strategy states:
* *Handover phase*: When $DTE \le 6$, block new current-month trades and prepare next-month trades.
* *Safety net*: When $DTE \le 1$, forcibly close current-month positions to avoid compulsory physical delivery of equity shares.

`ExpiryCalendar` loads official NSE holidays from `config/nse_holidays.csv` and injects a deterministic `days_to_expiry` column into every candle DataFrame, ensuring the backtester makes rollover decisions on the exact legal settlement day.

---

## 6. Summary of Architectural Flow (Smart Incremental Cache)

```
[Strategy Request: NESTLEIND 15m (start_date to end_date)]
                        │
                        ▼
             ┌─────────────────────┐
             │  SmartCacheManager  │
             └──────────┬──────────┘
                        │
      Inspect Master Parquet Index (<2ms)
      Check (min_time, max_time)
                        │
                        ▼
            Missing Deltas Needed?
           ├── NO  (100% Cache Hit) ─────────────────────────┐
           │                                                 │
           └── YES (Left / Right / Disjoint Span)            │
                        │                                    │
                        ▼                                    │
             [Query Broker API for Delta]                    │
                        │                                    │
                        ▼                                    │
             [Merge, Deduplicate & Save]                     │
             (Lock-Protected Atomic Parquet)                 │
                        │                                    │
                        └────────────────────────────────────┤
                                                             ▼
                                                [Slice Exactly to Window]
                                                             │
                                                             ▼
                                                [Optional Resampling (e.g. 1h)]
                                                             │
                                                             ▼
                                                [ExpiryCalendar (DTE)]
                                                             │
                                                             ▼
                                                [Ready for Backtest!]
```
