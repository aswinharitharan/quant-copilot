# QuantCopilot Living Status & Context Registry

> **Purpose**: Read this file at the start of any new chat session to instantly restore full project context with minimal token usage.  
> **Last Updated**: 2026-11-13  
> **Current Active Phase**: Phase 1 (Core Quant & Execution Engine) + 52-Week Low Strategy Complete + 52-Week High Breakout Strategy Complete + Unified Orchestrator Complete + 200 SMA Sideways Enhancements Verified; 129/129 tests passing  

---

## 📌 Executive Summary
- **Product**: Autonomous AI Quant Strategy Studio & Investor Marketplace.
- **Target Market**: Indian Equities, Futures & Options (NSE/MCX).
- **Primary Broker Integrations**:
  - **Angel One (SmartAPI)**: 100% Free broker-grade historical data (10+ years depth, 15m/1m OHLCV, automated 2FA TOTP login via `pyotp`). Primary market data feed.
  - **Dhan (DhanHQ)**: Trading API integration (execution and account management).
  - **Local PaperBroker**: Virtual low-latency execution engine for forward testing.
- **Architecture**: Conversational AI Copilot -> Declarative Strategy DSL -> Deterministic Backtester -> Deployment Handshake -> Risk Sentinel -> Broker Adapter -> Scanner & Sentinel Services -> MCP Servers -> Dual-Pane Web UI.

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
5. **Step 2D: Paper Broker & Risk Sentinel** (🔄 NEXT MILESTONE)
   - `src/brokers/paper_broker.py` & `src/risk/sentinel.py` (Virtual order execution, tick subscriber, Max Daily Loss kill-switch).

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




