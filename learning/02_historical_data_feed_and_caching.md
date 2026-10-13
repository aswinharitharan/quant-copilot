# Lesson 2: Historical Data Feed & Parquet Caching

**Modules:** `src/engine/data_feed.py`, `src/engine/expiry_calendar.py`, `src/engine/providers/yfinance_provider.py`

In quantitative finance, the quality and speed of your backtest are entirely dictated by how you ingest, store, and process market data. In this lesson, we explore how QuantCopilot solves data feeding, local caching, and Indian exchange calendar mechanics.

---

## 1. WHAT is the Data Feed Engine?

The Data Feed acts as the **fuel line** for the backtester:
* When a strategy requests: *"Give me 15-minute candles for NESTLEIND from 2024-01-01 to 2024-12-31"*, the Data Feed delivers clean, timezone-standardized (IST) OHLCV data.
* It operates on a **Cache-First principle**:
  1. Check local disk for a pre-saved `.parquet` file.
  2. If found, load it in ~10 milliseconds (zero network calls, zero rate-limiting).
  3. If missing, fetch from the data provider, save it to disk, and return it.

---

## 2. WHY an Abstract Base Class (`BaseDataProvider(ABC)`)?

In algorithmic trading, data sources change constantly:
* During offline prototyping, you want **free data** without API keys (`YFinanceProvider`).
* In production, you want **official 1-minute broker tick data** (`DhanHQProvider`).
* If you subscribe to institutional feeds, you want **tick-level archives** (`TrueDataProvider`).

### The Design Pattern: Dependency Inversion
If we hardcoded Yahoo Finance inside our backtester, switching to DhanHQ would require rewriting the backtester!

By defining an **Abstract Base Class (`BaseDataProvider`)**, we create a rigid contract:
```python
class BaseDataProvider(ABC):
    @abstractmethod
    def fetch_candles(self, symbol, exchange, interval, start_date, end_date) -> pd.DataFrame:
        pass
```

`DataFeed` only knows about `BaseDataProvider`. To swap providers, you change **exactly 1 line of configuration**:
```python
# Development mode:
feed = DataFeed(provider=YFinanceProvider())

# Live production mode:
feed = DataFeed(provider=DhanHQProvider(client_id="...", token="..."))
```
The caching, timeframe resampling, and backtesting math never change by a single line of code.

---

## 3. WHY Apache Parquet instead of Plain CSV?

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

## 6. Summary of Architectural Flow

```
[Strategy Request: NESTLEIND 15m]
            │
            ▼
    ┌───────────────┐
    │   DataFeed    │
    └───────┬───────┘
            │
      Cache Hit?
     ├── YES ──> [pd.read_parquet (~10ms)] ──┐
     │                                       │
     └── NO  ──> [BaseDataProvider Fetch]    │
                       │                     │
                 [Save .parquet]             │
                       │                     │
                       └─────────────────────┤
                                             ▼
                                  [Resample to 15m]
                                             │
                                             ▼
                                  [ExpiryCalendar (DTE)]
                                             │
                                             ▼
                                  [Ready for Backtest!]
```
