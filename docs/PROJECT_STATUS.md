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
| **Phase 1** | Quant Engine, Backtester, Paper Broker & Risk Sentinel | 🔄 In Progress | Milestone 1.2: Historical Data Feed & Caching |
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
   - **Equities & Futures**: Multi-year 1-minute historical data cached in `.parquet` format.
   - **Options**: Curated Nifty/BankNifty 1-minute options archives + Spot-driven Black-Scholes Greeks model for prototyping + Daily live tick recording via DhanHQ to grow a proprietary database.

---

## 🎯 Next Immediate Action Items (For the Next Chat Window)

When starting in the new window, focus on **Phase 1, Step 2**:

1. **~~Implement `src/schema/strategy.py`~~** (✅ DONE):
   - Pydantic models for `Leg`, `ConditionNode`, `StrategySet`, `DeploymentSettings`, and `StrategyDefinition`.
2. **Implement `src/engine/data_feed.py`**:
   - Historical candle fetcher with high-speed Parquet local cache.
3. **Implement `src/engine/backtester.py`**:
   - Deterministic backtester accounting for STT, exchange turnover fees, and slippage buffer.
4. **Implement `src/brokers/paper_broker.py` & `src/risk/sentinel.py`**:
   - Virtual order execution loop and Max Daily Loss emergency kill-switch.
