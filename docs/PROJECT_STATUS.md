# QuantCopilot Living Status & Context Registry

> **Purpose**: Read this file at the start of any new chat session to instantly restore full project context with minimal token usage.  
> **Last Updated**: 2026-11-20  
> **Current Active Phase**: Phase 1 (Core Quant & Execution Engine) + Step 2D.1 Broker Contracts & PaperBroker Complete; **154/154 tests passing**  

---

## 📌 Executive Summary
- **Product**: Autonomous AI Quant Strategy Studio & Investor Marketplace.
- **Target Market**: Indian Equities, Futures & Options (NSE/MCX).
- **Primary Broker Integrations**:
  - **Angel One (SmartAPI)**: 100% Free broker-grade historical data (10+ years depth, 15m/1m OHLCV, automated 2FA TOTP login via `pyotp`). Primary market data feed.
  - **Fyers (API v3)**: Primary live execution engine & forward-testing broker (100% Free Standard API, sub-50ms execution OMS, dedicated WebSocket Order & Trade Sockets, Futures Chain API for seamless MCX rollover, and native Market Price Protection).
  - **Local PaperBroker**: Virtual low-latency execution engine for forward testing and dry-run validation.
  - **DhanHQ / Zerodha Kite**: Secondary/Optional execution adapters (Dhan retains free order API but requires ₹499/mo data; Zerodha Personal tier is ₹0 for orders but ₹500/mo for data/ticks).
- **Architecture**: Conversational AI Copilot -> Declarative Strategy DSL -> Deterministic Backtester -> Deployment Handshake -> Risk Sentinel -> Broker Adapter -> Scanner & Sentinel Services -> MCP Servers -> Dual-Pane Web UI.

---

## 🚦 Roadmap Progress

| Phase | Milestone Name | Status | Next Milestone |
| :--- | :--- | :--- | :--- |
| **Phase 0** | Architecture, Scaffolding, Documentation & Basement | ✅ Complete | Ready for Phase 1 implementation |
| **Phase 1** | Quant Engine, Backtester, Paper Broker & Risk Sentinel | 🔄 In Progress | Step 2D.2: Lean Risk Sentinel (Account Kill-Switch & Airbag) |
| **Phase 2** | Skills & MCP Modularization | ⏳ Pending | Expose Engine as MCP Server |
| **Phase 3** | Web App Platform (Chat Copilot + Visual Dynamic Canvas) | ⏳ Pending | Full-stack Web UI Development |
| **Phase 4** | Consumer Marketplace & Strategy Recommendation Engine | ⏳ Pending | Investor matching algorithm & catalog |

---

## 📋 Architectural Decisions & Insights Log


1. **Declarative Strategy DSL over Raw Code Generation**
   - LLMs generate structured Pydantic models (Sets, Conditions, Legs, Universal Exit), NOT arbitrary Python execution scripts. Guarantees safety, syntax validity, and prevents lookahead bias.

2. **Fyers API v3 Selected as Primary Live Execution Broker**
   - 100% Free Standard Plan for live order execution, sub-50ms OMS roundtrips, dedicated Order & Trade WebSockets for instant fill confirmations (zero REST polling lag), dedicated `futures_chain` API for automated MCX Aluminium rollover, and native Market Price Protection (MPP).

3. **Broker Adapter Pattern (`BaseBroker`)**
   - Decouples strategy logic from brokers. Seamlessly swaps between `PaperBroker`, `FyersBroker`, `AngelBroker`, and optional `DhanClient`/`ZerodhaClient`.

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

9. **Independence from Tradetron & Native Direct Broker API Architecture**
   - Tradetron is recognized purely as a historical benchmark reference and potential third-party distribution marketplace; QuantCopilot operates as a self-contained autonomous quant platform.
   - Eliminates Tradetron subscription fees (₹1,500–₹3,000/month), execution queue latency (1–3 min delays), and clunky block-building UI. Direct broker connections execute in milliseconds.

10. **Updated True Zero-Broker-Tax Model (Angel One Data + Fyers Execution)**
    - Re-evaluated in Nov 2026: DhanHQ introduced a ₹499/mo fee for WebSocket data; Zerodha charges ₹500/mo for Kite Connect data (though Personal plan is ₹0 for orders).
    - QuantCopilot leverages a **Dual Zero-Cost Institutional Stack**:
      - **Angel One (SmartAPI)**: 100% Free 10+ year historical data + automated TOTP 2FA headless login (primary data feed & backtesting).
      - **Fyers (API v3)**: 100% Free execution OMS + dedicated Order Sockets + clean MCX futures symbology + automated headless 2FA (primary execution).
    - Single-Broker Option: Users can also run 100% on Angel One alone (both data and execution) or 100% on Fyers alone.
    - Decoupled via `BaseBroker` adapter pattern: Zerodha/Dhan/Upstox remain supported as optional connectors without altering core quant logic.

11. **Cloud-First Execution & Workplace Laptop Boundary (Mandatory Static IP)**
    - Personal automated trading bots must **never run on work/office laptops** due to enterprise IT policies, monitoring software, and sleep/lockout policies that sever order loops.
    - **SEBI Mandatory Static IP**: All major Indian brokers (Angel One, Fyers, Zerodha, Dhan) now mandate a registered Static IP for API order placement. Running from home or laptop dynamic IPs is prohibited by exchange gateways.
    - QuantCopilot is architected to run 24/7 headlessly on a budget cloud VPS (e.g. **Vultr Mumbai ~₹300–₹600/mo** or AWS Mumbai with Elastic IP) featuring:
      - Dedicated public Static IPv4 whitelisted with broker portals.
      - Sub-10ms ping to NSE/MCX Mumbai data centers.
      - Lightweight Ubuntu 22.04 LTS headless service managed by `systemd`.
      - Instant Telegram push alerts for order fills, circuit breakers, and daily briefings to the user's mobile phone.

12. **MCX Commodity Microstructure & Compulsory Delivery Safeguards**
    - MCX Base Metal futures (e.g. Aluminium 5 MT Big Lot / 1 MT Mini Lot) differ fundamentally from equities:
      - Continuous global price discovery (9:00 AM to 11:30 PM IST = 58 15m bars/day) eliminates opening gap traps.
      - **Tender Period Danger Zone**: 5 trading days prior to contract expiry, compulsory physical delivery rules apply. Holding into tender period causes massive margin spikes (up to 100%) and severe penalty charges.
      - **Mandatory Rollover Rule**: All positions in expiring contracts must exit cleanly at **`DTE <= 6`** (before the tender period begins), transferring new entries to the next-month contract.
      - **Session Filter**: Morning session (09:00–13:00) has thin domestic liquidity and frequent whipsaws. Restricting entries to the **London/NY active overlap window (13:00–22:30 IST)** dramatically boosts win rate and net profit.

13. **Multi-Tenant SaaS Architecture & Webhook-Driven Kill-Switch (Phases 3 & 4)**
    - Long-term commercialization uses a **Master Signal Dispatcher (Fan-Out)** pattern:
      - The strategy engine computes 15m indicators once for the market.
      - On signal firing, the system queries the active subscriber database (`status = 'ACTIVE' AND expiry_date >= NOW()`) and dispatches concurrent async orders to individual broker accounts.
      - **Automated Plug-Off / Kill-Switch**: Webhook listeners (Razorpay/Stripe) immediately flip status to `'EXPIRED'` upon payment lapse or cancellation, instantly pausing execution on that user's account.

14. **4-Pillar Quantitative Stock Selection Framework**
    - Quantitatively screens candidate symbols before deploying trend-following systems to avoid whipsaw graveyards:
      1. *Low Crossing Frequency*: < 6–8 crosses of 200 SMA per year on daily data.
      2. *Trend Fuel*: ADX(14) > 25 for at least 40%+ of historical bars.
      3. *High Efficiency*: Kaufman Efficiency Ratio (KER 60) > 0.18–0.35 (smooth directional thrusts).
      4. *Volatility Headroom*: Daily ATR% > 2.5% (or 15m ATR% > 0.45%) so gains comfortably swamp transaction friction.
    - Empirical 192-stock Nifty 200 screen completed in `data/reports/nifty200_trend_efficiency_ranking.csv` and documented in `STOCK_SELECTION_GUIDE.md` (Top picks: DIVISLAB, MCX, BHEL, MOTHERSON, OFSS, LAURUSLABS).

15. **Absolute Institutional Liquidity Floor & Turnover Gate (52W Scanners)**
    - Relative volume anomaly filters ($\ge 3\times$ SMA volume) suffer from a critical "low denominator" vulnerability on illiquid micro-caps / ghost stocks (e.g. 45 shares vs 9 share baseline $= 5\times$ anomaly, but only ₹5 Lakhs daily turnover).
    - Enforces hard automated liquidity firewalls across both `LowCapitulationScanner` and `HighBreakoutScanner`:
      - **`MIN_AVG_DAILY_VOLUME = 5,000`** shares/day minimum baseline.
      - **`MIN_DAILY_TURNOVER_INR = ₹50,00,000`** (₹50 Lakhs) minimum turnover on anomaly or average day.
    - Eliminates untradeable illiquid traps from ever reaching user radar, watchlist, or portfolio prompts.

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
   - [`src/engine/indicators.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/indicators.py) (Pure vectorized SMA, EMA, RSI, VWAP, ATR, Supertrend, ADX, SMA_ENVELOPE).
   - [`src/engine/condition_evaluator.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/condition_evaluator.py) (Anti-lookahead ConditionTree evaluator with shift(1) crossing logic).
   - [`src/engine/costs.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/costs.py) (Indian market STT, exchange fees, GST, SEBI, stamp duty, slippage).
   - [`src/engine/backtester.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/backtester.py) & [`src/schema/backtest_models.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/schema/backtest_models.py) (Bar-by-bar execution loop, intraday/positional lifecycle, circuit breakers, post-loss re-entry cooldown).
   - [`src/engine/metrics.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/metrics.py) (CAGR, Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Expectancy).
   - Benchmark Implementation & Validation: [`src/strategies/nestle_200_sma.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/nestle_200_sma.py), [`src/strategies/nestle_200_sma_enhanced.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/nestle_200_sma_enhanced.py) & [`tests/test_benchmark_nestle.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_benchmark_nestle.py).
   - Head-to-Head Benchmark Runner: [`scripts/run_enhanced_comparison.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_enhanced_comparison.py) demonstrating +₹12.13L turnaround from negative to positive alpha across NESTLEIND, HINDUNILVR, and ALKEM (129/129 tests passing).
4. **Step 2C: Smart Incremental Master Cache & Extended Backtests** (✅ COMPLETE)
   - [`src/engine/smart_cache.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/smart_cache.py): Range-aware smart cache manager (`SmartCacheManager`).
   - Lightning-fast (<2ms) time range inspection using PyArrow column projection without reading entire datasets.
   - Intelligent delta interval calculation (left/prepend, right/append, disjoint) so only missing calendar dates are queried from the broker API.
   - Clean single-file master Parquet format (`data/cache/{symbol}_{exchange}_{interval}.parquet`) with embedded schema/index metadata (zero `.meta.json` clutter).
   - Atomic merge and write with cross-process file locking via standard library `fcntl.flock`.
   - Runtime provider resolution (Angel One SmartAPI default, DhanHQ, YFinance, or custom instance).
   - Automated cache pruning/retention policy (`prune_cache` by age and disk budget with master file protection).
   - Tests: [`tests/test_smart_cache.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_smart_cache.py) (9/9 tests passing; 66/66 total suite passing).
5. **Step 2D: Broker Layer, Risk Sentinel & Live Cloud Execution (Phased Breakdown)** (🔄 IN PROGRESS)
   - **Step 2D.1: Unified Broker Contracts & Local Paper Broker Engine** (✅ COMPLETE)
     - [`src/brokers/base.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/brokers/base.py): Abstract `BaseBroker` interface (`place_order`, `cancel_order`, `get_positions`, `get_balance`, `subscribe_ticks`) and Pydantic models (`OrderRequest`, `OrderResponse`, `Position`, `AccountBalance`, `OrderStatus`, `ProductType`).
     - [`src/brokers/paper_broker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/brokers/paper_broker.py): High-fidelity virtual execution engine with dynamic order matching (LIMIT/MARKET), mark-to-market valuations, position lifecycle (open, add, reduce, flip), margin validation, and transaction friction via `TransactionCostModel`.
     - Tests: [`tests/test_paper_broker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_paper_broker.py) (10/10 tests passing; **153/153 total project suite passing**).
     - *Dependency: 100% local, zero external credentials or cloud accounts required.*
   - **Step 2D.2: Lean Risk Sentinel (Pure Account-Level Kill-Switch & Airbag)** (🔄 NEXT MILESTONE)
     - `src/risk/sentinel.py`: Ultra-lean broker proxy focused strictly on total account capital preservation (strategy-specific exits/stops stay 100% inside individual strategies).
     - Implements 3 core capabilities:
       1. **Master Emergency Kill-Switch (`kill_all()` / `/kill`)**: Cancels all open orders on the broker, flattens all open positions across the account at market price, disconnects the runner, and locks trading for the day.
       2. **Automated Loss Airbag (`max_daily_loss` tripwire)**: Configurable threshold (INR or % of margin/equity, e.g. ₹3,500 / 4.5%–5% for MCX Aluminium Mini Lot). Automatically trips the Master Kill-Switch if total account daily loss breaches the threshold.
       3. **Session Lock & Auto-Reset**: Persists lock state to disk for the rest of today; automatically resets at 08:30 AM next morning for the new trading day (with manual `--unlock` override).
     - Tests: `tests/test_risk_sentinel.py` (manual kill switch, automated airbag tripwire, lock persistence, and morning auto-reset).
     - *Dependency: Builds directly on Step 2D.1.*
   - **Step 2D.3: Live 15m Candle Aggregator & Paper Strategy Runner**
     - `src/engine/live_candle_aggregator.py`: Ingests raw market ticks and dynamically constructs completed 15-minute OHLCV bars.
     - `src/engine/live_runner.py`: Event-driven execution loop connecting the MCX Aluminium Enhanced 200 SMA strategy, `RiskSentinel`, and `PaperBroker`.
     - Script: `scripts/run_paper_mcx_aluminium.py` for testing paper execution locally or in the cloud.
     - Tests: `tests/test_live_runner.py`.
     - *Dependency: Ingests live WebSocket ticks from Angel One or Fyers.*
   - **Step 2D.4: Live Broker API Adapter (Fyers API v3)**
     - `src/brokers/fyers_broker.py`: Concrete `BaseBroker` implementing Fyers API v3.
     - Headless 2FA login (automated TOTP via `pyotp`), order placement with Market Price Protection (MPP), dedicated Order/Trade WebSocket push listeners (sub-50ms fill notifications), and `futures_chain` contract resolution.
     - Tests: `tests/test_fyers_broker.py` (mocked HTTP/WS test suite + live integration tests).
     - *Dependency: Fyers trading account and API credentials.*
   - **Step 2D.5: Cloud Deployment & Process Guardian (24/7 Always-On)**
     - `src/alerts/telegram_notifier.py`: Instant mobile push alerts for order fills, target hits, stop-loss exits, and circuit breaker events.
     - `deploy/`: Headless VPS setup script (`deploy.sh`), `systemd` service configuration (`quantcopilot.service` for automatic crash restart and startup on boot).
     - Static IP Whitelisting Guide for broker developer portals.
     - *Dependency: Cloud VPS instance (e.g. Vultr Mumbai or AWS Mumbai).*

---

## 🏹 Institutional Strategies Registry

### 1. 52-Week Low Capitulation Strategy ([`docs/STRATEGY_52_WEEK_LOW.md`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/STRATEGY_52_WEEK_LOW.md))
- **Concept**: Detects panic selling absorbed by institutions at 52-week lows on abnormal volume ($3\times$ to $20\times$ 20-day SMA volume), backed by Screener.in solvency screening and SEBI PIT promoter buying.
- **Interactive Lifecycle**: Radar Discovery $\to$ User Watchlist (Tier 1) $\to$ Stage 2 Buy Confirmation $\to$ Active Portfolio Tracking (Tier 2 with Soft Stop-Loss & Target 1/2) $\to$ Permanent Closed Trade Ledger (Tier 3).
- **Progress Status**:
  - **Phase A: Architecture, Data Contracts & Fundamental / Insider Engines** (✅ COMPLETE)
    - [`src/scanner/models.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/models.py): Pydantic data models for audit, insider trades, signals, watchlist, portfolio, and trade ledger.
    - [`src/scanner/screener_client.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/screener_client.py): Screener.in scraper enforcing 5 Golden Rules (0% pledge, D/E < 0.6, Int Coverage > 3.5, CFO > 0, ROCE >= 12%).
    - [`src/scanner/insider_feed.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/insider_feed.py): NSE SEBI PIT parser filtering material promoter open-market purchases ($\ge$ ₹1 Cr).
    - Tests: [`tests/test_screener_client.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_screener_client.py) & [`tests/test_insider_feed.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_insider_feed.py) (7/7 tests passing; 73/73 total project suite passing).
  - **Phase B: Technical Engine & Two-Stage State Machine** (✅ COMPLETE)
    - [`src/scanner/low_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/low_scanner.py): `LowCapitulationScanner` implementing the 3-step funnel (NSE 52W-low discovery, Screener fundamental audit, targeted OHLCV analysis for volume anomaly $3\times$ to $20\times$, automated support/EMA targets, and Stage 2 buy confirmation state machine).
    - Tests: [`tests/test_52_low_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_52_low_scanner.py) (8/8 tests passing; 81/81 total project suite passing).
  - **Phase C: Watchlist, Portfolio Tracker, Soft Stop & Target Sentinel** (✅ COMPLETE)
    - [`src/scanner/tracker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/tracker.py): `PortfolioTracker` managing 3-tier JSON storage (`data/watchlist_52_low.json`, `data/portfolio_52_low.json`, `data/trade_history_52_low.json`), contextual event audit notes (`history_notes`), cascading capitulation resets, partial scaling (50% book at T1, 50% at T2), auto-archiving, and daily status badges (`SAFE`, `RADAR_ALERT`, `DECISION_REQD`, `TARGET_1_HIT`, `TARGET_2_HIT`).
    - Tests: [`tests/test_tracker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_tracker.py) (5/5 tests passing; 86/86 total project suite passing).
  - **Phase D: Conversational Trigger ('Whats today for 52') & CLI Runner** (✅ COMPLETE)
    - [`src/scanner/service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/service.py): `ScannerService` unified facade tying together technical scanner, fundamental auditor, insider feed, portfolio tracker, fast lightweight queries (`portfolio`, `watchlist`), and Markdown executive briefing formatting.
    - [`scripts/run_52_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_52_scanner.py): Modular CLI runner supporting `daily`, `portfolio`, `watchlist`, `audit`, `buy`, and `sell` subcommands with `--offline` / `--skip-prices` support.
    - Hardened with top-level try/except logging, symbol whitelist regex, cache TTL constants, random User-Agent fallback, and 404/429 fallback.
    - Tests: [`tests/test_scanner_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_scanner_service.py) & [`tests/test_52_low_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_52_low_scanner.py) (Full test suite: 103/103 tests passing).

### 2. Public API Reference (`ScannerService`)

| Method | Signature | Description |
| :--- | :--- | :--- |
| `get_daily_briefing` | `(candidate_symbols=None, as_of_date=None, skip_fundamental_audit=False, current_prices=None) -> DailyDashboard52` | End-to-end evening executive dashboard (discovery, watchlist triggers, portfolio sentinels, insider trades). |
| `format_daily_briefing_markdown` | `(dashboard: DailyDashboard52) -> str` | Formats the briefing payload into an executive Markdown report. |
| `scan_radar_candidates` | `(candidate_symbols=None, as_of_date=None) -> Tuple[List[CapitulationSignal], str]` | Focused discovery & audit of 52W-low capitulation candidates without altering portfolio state. |
| `get_portfolio_summary` | `(current_prices=None, as_of_date=None) -> Tuple[List[PortfolioStock], str]` | Fast check of active Tier 2 holdings, soft stop-loss buffers, and PnL badges. |
| `get_watchlist_summary` | `(as_of_date=None) -> Tuple[List[WatchlistStock], str]` | Reviews Tier 1 watchlist and evaluates Stage 2 confirmation triggers against latest price bars. |
| `audit_single_symbol` | `(symbol: str, df=None) -> Dict[str, Any]` | Deep dive on a single ticker: fundamentals, insider activity, and technical levels. |
| `record_buy` | `(symbol, entry_price, quantity, entry_date=None, notes=None) -> PortfolioStock` | Records order execution into Tier 2 Active Portfolio. |
| `record_sell` | `(symbol, sell_price, quantity, reason, sell_date=None, notes=None) -> Tuple[PortfolioStock, Optional[ClosedTradeLedger]]` | Records partial or full exit and archives completed trades to Tier 3 Ledger. |

> **Note on Internal Helpers**:  
> Convenience methods such as `add_to_watchlist` and `remove_from_watchlist` are internal helper proxies to `PortfolioTracker`. They facilitate interactive CLI execution and scripting, but are **not** part of the published Model Context Protocol (MCP) tool contract.

### 3. 52-Week High Breakout Strategy ([`docs/STRATEGY_52_WEEK_HIGH.md`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/STRATEGY_52_WEEK_HIGH.md))
- **Concept**: Institutional Breakout Accumulation (IBA) & Stage 2 Growth. 4-layer qualification funnel (52W high proximity, VCP base structure, volume expansion, growth fundamentals screen via Screener.in), Exhaustion Climax Guard (veto on blowoff tops), and dynamic trailing 20 EMA ratchet.
- **Interactive Lifecycle**: Radar Discovery $\to$ User Watchlist (Tier 1) $\to$ Stage 2 Buy Confirmation (close above pivot high) $\to$ Active Portfolio Tracking (Tier 2 with Trailing 20 EMA Sentinel & Target 1/2) $\to$ Permanent Closed Trade Ledger (Tier 3).
- **Progress Status**: ✅ **PRODUCTION-READY — All Phases (A, B, C, D) Complete** (122/122 total project suite passing).
  - [`src/scanner/models.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/models.py): Pydantic data models for breakout signals, base metrics, exhaustion metrics, watchlist, portfolio, and dashboard.
  - [`src/scanner/screener_client.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/screener_client.py): Fundamental growth audit (Sales YoY $\ge 10\%$, Profit YoY $\ge 12\%$, ROCE $\ge 12\%$, D/E $< 1.0$, Promoter Holding $\ge 40\%$, Pledge $< 15\%$).
  - [`src/scanner/high_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/high_scanner.py): `HighBreakoutScanner` implementing 4-layer funnel, VCP base detection, exhaustion guard, and Stage 2 confirmation state machine.
  - [`src/scanner/high_tracker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/high_tracker.py): `HighPortfolioTracker` managing 3-tier JSON architecture (`data/watchlist_52_high.json`, `data/portfolio_52_high.json`, `data/trade_history_52_high.json`), trailing 20 EMA ratchet, partial exits (+15% T1, +30% T2), and auto-archiving.
  - [`src/scanner/high_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/high_service.py): `HighScannerService` unified facade for `"Whats today for 52 High"` briefings.
  - [`scripts/run_52_high_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_52_high_scanner.py): Full CLI runner supporting `daily`, `radar`, `portfolio`, `watchlist`, `audit`, `buy`, and `sell`.

### 4. Unified 52-Week Strategy Orchestrator ([`src/scanner/unified_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/unified_service.py))
- **Concept**: Single conversational entry point for `"whats today for 52"`. Orchestrates both 52-Week Low Capitulation (`ScannerService`) and 52-Week High Breakout (`HighScannerService`), merging discovery radars, stage 2 buy triggers, active holdings sentinels, and deduplicated SEBI PIT promoter buying into a unified executive Markdown briefing.
- **CLI Dispatcher**: [`scripts/run_52_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_52_scanner.py) with `--strategy {both,high,low}` (defaults to `both`).
- **Tests**: [`tests/test_unified_scanner_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_unified_scanner_service.py) (4/4 tests passing; **126/126 total project test suite passing**).

### 6. 52-Week High Institutional Exhaustion & Day 2 Intraday MIS Short Strategy ([`docs/STRATEGY_52_WEEK_HIGH_SHORT.md`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/STRATEGY_52_WEEK_HIGH_SHORT.md))
- **Concept**: Wyckoff Upthrust After Distribution (UTAD) / Institutional Bull Trap short selling strategy.
  - **Day 1 Climax Discovery (Radar)**: Touches new 52-week high + volume $\ge 3\times$ 20-day average + upper rejection wick $\ge 45\%$ + weak close in bottom 40% of daily range + parabolic extension $\ge 20\%$ above 50 EMA + turnover $\ge ₹50$ Cr liquidity floor.
  - **Day 2 Breakdown Confirmation (State Machine)**: Intraday MIS short triggers only when morning price cracks Day 1 Climax Low (selling into established weakness rather than picking the top).
  - **Phase 1 Execution Vehicle**: Cash Intraday MIS (Exit before 03:10 PM, 0% overnight gap risk). Invalidation stop at Day 2 open high or Climax High + 0.3%, Target 1 at -2.0% (book 50%), Target 2 at -4.0% (book 100%).
  - **Unified Conversational UX**:
    - `"Whats today for 52"`: Multi-strategy briefing with Section A (High Long), Section B (Low Long), Section C (High Exhaustion Short MIS), and Section D (SEBI PIT Promoter Buying).
    - `"52 watchlist"`: Automatically renders 3 distinct, dedicated tables (Low, High, Short) without prompting the user.
    - `"52 portfolio"`: Automatically separates Positional Delivery Long Holdings from Active Intraday MIS Shorts.
- **Production Modules**:
  - Models: [`src/scanner/models.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/models.py) (`ShortSignalStage`, `ShortExitReason`, `ExhaustionShortSignal`, `ShortWatchlistStock`, `ShortTradeRecord`, `DailyDashboard52Short`).
  - Technical Scanner: [`src/scanner/short_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/short_scanner.py) (`HighExhaustionShortScanner`).
  - Portfolio & Watchlist Tracker: [`src/scanner/short_tracker.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/short_tracker.py) (`ShortPortfolioTracker` with `data/watchlist_52_short.json` and `data/trade_history_52_short.json`).
  - Service Facade: [`src/scanner/short_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/short_service.py) (`ShortScannerService`).
  - Unified Orchestrator: [`src/scanner/unified_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/scanner/unified_service.py) (`get_unified_daily_briefing()`, `get_unified_watchlist()`, `get_unified_portfolio()`).
  - Standalone & Unified CLI: [`scripts/run_52_short_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_52_short_scanner.py) and [`scripts/run_52_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_52_scanner.py).
  - Documentation: [`docs/STRATEGY_52_WEEK_HIGH_SHORT.md`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/STRATEGY_52_WEEK_HIGH_SHORT.md).
- **Test Suite**: [`tests/test_52_short_scanner.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_52_short_scanner.py) & [`tests/test_unified_scanner_service.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_unified_scanner_service.py) (**142/142 total project tests passing**).

- **Concept**: Vectorized and event-driven trend-following engine designed for Indian stock and commodity futures (15m candles). Overcomes the catastrophic ~70% sideways whipsaw trap of raw 200 SMA by introducing 5 institutional filtering layers:
  1. **ATR Dead-Zone Envelope**: $SMA(200) \pm 1.0 \times ATR(14)$. Entries only permitted outside the envelope; early exits allowed at the 200 SMA line to protect profits.
  2. **ADX Regime Gate**: Requires $ADX(14) > 22$ (Equities) or $ADX(14) > 25$ (MCX Aluminium) to filter out flat consolidation.
  3. **Post-Loss Cooldown**: Enforces an 8-bar (2-hour) waiting window after any losing trade before evaluating new entries.
  4. **Active Session Window**: Restricts entries to high-liquidity hours (13:00 to 22:30 IST for MCX Aluminium to align with London/NY overlap).
  5. **Tender Period & Rollover Safety Net**: Mandates exit and handover to next-month contract at $DTE \le 6$ to completely eliminate compulsory delivery penalties.
- **Empirical Backtest Validations**:
  - **NSE Stock Futures**: Turned NESTLEIND from -₹5.98L to +₹92k, HINDUNILVR from -₹1.18L to +₹156k, and ALKEM from -₹1.78L to +₹70k (+₹12.13L total turnaround across 3 stocks). Runner: [`scripts/run_enhanced_comparison.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_enhanced_comparison.py).
  - **MCX Aluminium Futures**: Verified across 13,244 real 15m candles (Nov 2025 to Nov 2026, `data/cache/MCX_ALUMINIUM_15m_2025_2026.parquet`). Turned raw 200 SMA from -₹8,61,696 to **+₹1,98,488** (+₹10,60,183 Alpha gain; trades reduced from 440 to 189; win rate increased from 12.3% to 33.9%).
- **Artifacts & Production Deliverables**:
  - Dedicated Strategy Modules:
    - [`src/strategies/nestle_200_sma_enhanced.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/nestle_200_sma_enhanced.py)
    - [`src/strategies/hindunilvr_200_sma_enhanced.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/hindunilvr_200_sma_enhanced.py)
    - [`src/strategies/alkem_200_sma_enhanced.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/alkem_200_sma_enhanced.py)
    - [`src/strategies/mcx_aluminium_200_sma_enhanced.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/strategies/mcx_aluminium_200_sma_enhanced.py) (Supports 5 MT Big Lot and 1 MT Mini Lot).
  - Multi-Tab Excel Workbook: [`data/exports/MCX_ALUMINIUM_15m_2025_2026.xlsx`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/data/exports/MCX_ALUMINIUM_15m_2025_2026.xlsx) (Strategy Comparison, Yearly Performance, All Trades Log with 189 trades, Market Data Summary, and 15m Candles).
  - Runner Scripts: [`scripts/run_mcx_aluminium_backtest.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/run_mcx_aluminium_backtest.py) and [`scripts/export_mcx_aluminium_excel.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/scripts/export_mcx_aluminium_excel.py).
  - Test Suite: [`tests/test_mcx_aluminium.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_mcx_aluminium.py) (**131/131 total test suite passing**).
  - Stock Selection Guide: [`data/reports/nifty200_trend_efficiency_ranking.csv`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/data/reports/nifty200_trend_efficiency_ranking.csv) & `STOCK_SELECTION_GUIDE.md` (Top candidates: DIVISLAB, MCX, BHEL, MOTHERSON, OFSS, LAURUSLABS).





