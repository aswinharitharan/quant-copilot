# QuantCopilot Living Status & Context Registry

> **Purpose**: Read this file at the start of any new chat session to instantly restore full project context with minimal token usage.  
> **Last Updated**: 2026-10-06  
> **Current Active Phase**: Phase 1 (Core Quant & Execution Engine) - IN PROGRESS (Step 1 Complete)  

---

## 📌 Executive Summary
- **Product**: Autonomous AI Quant Strategy Studio & Investor Marketplace.
- **Target Market**: Indian Equities, Futures & Options (NSE/MCX).
- **Primary Broker Integration**: **Dhan (DhanHQ)** (Free APIs & Historical Data) + Local **PaperBroker**.
- **Architecture**: Conversational AI Copilot -> Declarative Strategy DSL -> Deterministic Backtester -> Deployment Handshake -> Risk Sentinel -> Broker Adapter -> MCP Servers -> Dual-Pane Web UI.

---

## 🚦 Roadmap Progress

| Phase | Milestone Name | Status | Next Milestone |
| :--- | :--- | :--- | :--- |
| **Phase 0** | Architecture, Scaffolding, Documentation & Basement | ✅ Complete | Ready for Phase 1 implementation |
| **Phase 1** | Quant Engine, Backtester, Paper Broker & Risk Sentinel | 🔄 In Progress | Milestone 1.3: Deterministic Backtest Engine (Step 2B) |
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
   - [`src/engine/providers/yfinance_provider.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/providers/yfinance_provider.py) (Offline-first / dev provider).
   - [`src/engine/expiry_calendar.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/src/engine/expiry_calendar.py) + [`config/nse_holidays.csv`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/config/nse_holidays.csv) (NSE last-Thursday expiry rules, holiday adjustment, DTE calculation).
   - Tests: [`tests/test_data_feed.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_data_feed.py) & [`tests/test_expiry_calendar.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_expiry_calendar.py) (16/16 tests passing).
   - Educational Lesson: [`learning/02_historical_data_feed_and_caching.md`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/learning/02_historical_data_feed_and_caching.md).
3. **Step 2B: Deterministic Backtest Engine** (🔄 NEXT UP)
   - `src/engine/backtester.py` (Condition evaluator, STT, exchange turnover fees, GST, stamp duty, slippage buffer, CAGR/Sharpe/Drawdown metrics).
4. **Step 2C: Paper Broker & Risk Sentinel**
   - `src/brokers/paper_broker.py` & `src/risk/sentinel.py` (Virtual order execution, tick subscriber, Max Daily Loss kill-switch).
5. **Step 2D: Batch Stress Test & Benchmark Validation**
   - 50–100 strategy programmatic stress-test battery + official Nestle India 200 SMA E2E backtest.


