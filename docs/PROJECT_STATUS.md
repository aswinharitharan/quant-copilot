# QuantCopilot Living Status & Context Registry

> **Purpose**: Read this file at the start of any new chat session to instantly restore full project context with minimal token usage.  
> **Last Updated**: 2026-11-05  
> **Current Active Phase**: Phase 1 (Core Quant & Execution Engine) - Step 2C Smart Cache Complete; 66/66 tests passing  

---

## 📌 Executive Summary
- **Product**: Autonomous AI Quant Strategy Studio & Investor Marketplace.
- **Target Market**: Indian Equities, Futures & Options (NSE/MCX).
- **Primary Broker Integrations**:
  - **Angel One (SmartAPI)**: 100% Free broker-grade historical data (10+ years depth, 15m/1m OHLCV, automated 2FA TOTP login via `pyotp`). Primary market data feed.
  - **Dhan (DhanHQ)**: Trading API integration (execution and account management).
  - **Local PaperBroker**: Virtual low-latency execution engine for forward testing.
- **Architecture**: Conversational AI Copilot -> Declarative Strategy DSL -> Deterministic Backtester -> Deployment Handshake -> Risk Sentinel -> Broker Adapter -> MCP Servers -> Dual-Pane Web UI.

---

## 🚦 Roadmap Progress

| Phase | Milestone Name | Status | Next Milestone |
| :--- | :--- | :--- | :--- |
| **Phase 0** | Architecture, Scaffolding, Documentation & Basement | ✅ Complete | Ready for Phase 1 implementation |
| **Phase 1** | Quant Engine, Backtester, Paper Broker & Risk Sentinel | 🔄 In Progress | Milestone 1.4: Paper Broker & Risk Sentinel (Step 2D) |
| **Phase 2** | Skills & MCP Modularization | ⏳ Pending | Expose Engine as MCP Server |
| **Phase 3** | Web App Platform (Chat Copilot + Visual Dynamic Canvas) | ⏳ Pending | Full-stack Web UI Development |
| **Phase 4** | Consumer Marketplace & Strategy Recommendation Engine | ⏳ Pending | Investor matching algorithm & catalog |

---

## 📋 Architectural Decisions & Insights Log


1. **Declarative Strategy DSL over Raw Code Generation**
   - LLMs generate structured Pydantic models (Sets, Conditions, Legs, Universal Exit), NOT arbitrary Python execution scripts. Guarantees safety, syntax validity, and prevents lookahead bias.

2. **DhanHQ Selected as Primary Indian Broker API**
   - Free trading API, free 1-minute historical candles, free WebSocket ticks, and zero subscription fees for end users.

3. **Broker Adapter Pattern (`BaseBroker`)**
   - Decouples strategy logic from brokers. Seamlessly swaps between `PaperBroker`, `DhanClient`, and future Zerodha/AngelOne clients.

4. **Institutional "Deployment Handshake" (Post-Backtest Gate)**
   - Before any strategy deploys (Paper or Live), the AI conducts a structured, conversational confirmation covering:
     - **Expiry Rollover**: Auto-rollover rule (e.g. 1 day before expiry at 2:30 PM) vs Square off.
     - **Position Sizing & Capital**: Allocated capital (e.g., ₹1,00,000) and Lot sizing mode.
     - **Risk Sentinels**: Max Daily Loss circuit breaker (e.g., -₹3,000) and Universal Exit target.
     - **Overtrading Guard**: Daily re-entry cap (e.g., max 2–3 trades/day).
     - **Order Precision**: Immediate-Fill Limit Order with 0.5%–1% buffer (mandated by Indian exchange algo rules on NSE/MCX).
     - **Market Open Gate**: Delay first trade check until 9:20 AM to avoid 9:15 AM opening spread traps.

5. **F&O Historical Data Strategy**
   - **Equities & Futures**: Multi-year 1-minute historical data cached locally in `.parquet` format (compressed, fast I/O, strict datetime types). Excluded from Git (`data/` in `.gitignore`) to prevent repo bloat.
   - **Daily Data**: Free deep history (20+ years back to listing date) via yfinance & DhanHQ for long-term positional backtests.
   - **Options Reality**: Curated Nifty/BankNifty 1-minute options archives + Spot-driven Black-Scholes Greeks model for prototyping + Daily live tick recording via DhanHQ WebSocket to build a proprietary options database over time.

6. **Golden Integration Benchmark Strategy (`docs/BENCHMARK_STRATEGY_NESTLEIND_200SMA.md`)**
   - **Nestle India SMA 200 (Tradetron ID: 10038358)**: 15m candles, 200 SMA on NSE Stock Futures with dual-contract handover (DTE <= 6 days handover, DTE <= 1 day safety exit, OPEN_POSITIONS == 0 guard). Used as the end-to-end integration and backtest validation target.

7. **Two-Stage QA & Product Quality Testing Strategy**
   - **Stage 1 (Before MCP / End of Phase 1)**: Programmatic batch stress test (`scripts/run_batch_test.py`) running 50–100 algorithmic strategy variations (trend following, mean reversion, opening range breakouts, short straddles, edge cases) directly through the Python engine to mathematically prove zero crashes, zero lookahead bias, and precise transaction cost calculations.
   - **Stage 2 (After MCP / Phase 2)**: Natural language conversational testing in chat to verify LLM translation accuracy, prompt flexibility, and MCP tool execution.

8. **Market Scanner / Screener Capabilities (Roadmap)**
   - The declarative `ConditionTree` (`ConditionGroup`, `ConditionNode`) naturally supports market screening (e.g., 52-week high, EMA crossovers) across Nifty 50/500 constituents on the latest candles. Planned as a first-class feature in Phase 2/3.

---

## 🎯 Phase 1 Detailed Execution Slices

We execute Phase 1 in clear, self-contained chunks:

1. **Step 1: Canonical Strategy Schema** (✅ COMPLETE)
   - [`src/schema/strategy.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/schema/strategy.py) + [`tests/test_strategy_schema.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_strategy_schema.py) (4/4 passing).
2. **Step 2A: Historical Data Feed & Caching** (✅ COMPLETE)
   - [`src/engine/data_feed.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/data_feed.py) (`BaseDataProvider`, `DataFeed`, Parquet cache, multi-timeframe resampling).
   - [`src/engine/providers/angel_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/providers/angel_provider.py) (Angel One SmartAPI: 100% Free broker-grade feed, 10+ yr depth, automated TOTP login, exponential rate-limit backoff, token resolution).
   - [`src/engine/providers/dhan_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/providers/dhan_provider.py) (DhanHQ provider).
   - [`src/engine/providers/yfinance_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/providers/yfinance_provider.py) (Offline fallback provider).
   - [`src/engine/expiry_calendar.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/expiry_calendar.py) + [`config/nse_holidays.csv`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/config/nse_holidays.csv) (NSE last-Thursday expiry rules, holiday adjustment, DTE calculation).
   - Tests: [`tests/test_data_feed.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_data_feed.py), [`tests/test_expiry_calendar.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_expiry_calendar.py), [`tests/test_angel_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_angel_provider.py), [`tests/test_dhan_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_dhan_provider.py) (30/30 tests passing).
   - Multi-year pipeline: [`scripts/fetch_and_export_5yr_nestle.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/fetch_and_export_5yr_nestle.py) (2022–2026, 29,290 candles, 0 unexpected missing days, Excel & Parquet exports).
   - **Upcoming Planned Enhancement**: Smart Incremental Master Cache (range-aware slicing & delta fetching to prevent duplicate API downloads).
3. **Step 2B: Deterministic Backtest Engine** (✅ COMPLETE)
   - [`src/engine/indicators.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/indicators.py) (Pure vectorized SMA, EMA, RSI, VWAP, ATR, Supertrend).
   - [`src/engine/condition_evaluator.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/condition_evaluator.py) (Anti-lookahead ConditionTree evaluator with shift(1) crossing logic).
   - [`src/engine/costs.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/costs.py) (Indian market STT, exchange fees, GST, SEBI, stamp duty, slippage).
   - [`src/engine/backtester.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/backtester.py) & [`src/schema/backtest_models.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/schema/backtest_models.py) (Bar-by-bar execution loop, intraday/positional lifecycle, circuit breakers).
   - [`src/engine/metrics.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/metrics.py) (CAGR, Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Expectancy).
   - Benchmark Implementation & Validation: [`src/strategies/nestle_200_sma.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/nestle_200_sma.py) & [`tests/test_benchmark_nestle.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_benchmark_nestle.py) (Full 57/57 total test suite passing).
   - Runners & Analyzers: [`scripts/run_nestle_angel_backtest.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_nestle_angel_backtest.py), [`scripts/run_nestle_5yr_angel_backtest.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_nestle_5yr_angel_backtest.py), [`scripts/add_backtest_to_excel.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/add_backtest_to_excel.py) (exports year-wise metrics & 493-trade log to Excel).
4. **Step 2C: Smart Incremental Master Cache & Extended Backtests** (✅ COMPLETE)
   - [`src/engine/smart_cache.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/smart_cache.py): Range-aware smart cache manager (`SmartCacheManager`).
   - Lightning-fast (<2ms) time range inspection using PyArrow column projection without reading entire datasets.
   - Intelligent delta interval calculation (left/prepend, right/append, disjoint) so only missing calendar dates are queried from the broker API.
   - Clean single-file master Parquet format (`data/cache/{symbol}_{exchange}_{interval}.parquet`) with embedded schema/index metadata (zero `.meta.json` clutter).
   - Atomic merge and write with cross-process file locking via standard library `fcntl.flock`.
   - Runtime provider resolution (Angel One SmartAPI default, DhanHQ, YFinance, or custom instance).
   - Automated cache pruning/retention policy (`prune_cache` by age and disk budget with master file protection).
   - Tests: [`tests/test_smart_cache.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_smart_cache.py) (9/9 tests passing; 66/66 total suite passing).
5. **Step 2D: Paper Broker & Risk Sentinel** (🔄 NEXT MILESTONE)
   - `src/brokers/paper_broker.py` & `src/risk/sentinel.py` (Virtual order execution, tick subscriber, Max Daily Loss kill-switch).


