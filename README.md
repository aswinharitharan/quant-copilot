# QuantCopilot (TradeAI Platform)

> **Autonomous AI Quant Strategy Studio & Investor Marketplace**
> *From Natural Language Strategy to Backtested, Risk-Managed Execution & Marketplace.*

---

## 🎯 Executive Vision
QuantCopilot bridges the gap between discretionary trading ideas and institutional-grade quantitative execution. 

1. **For Strategy Creators (Phase 1 & 2)**: Natural language strategy formulation, rigorous backtesting with walk-forward validation & transaction cost modeling, paper/live broker execution with hard risk sentinels, and modular export as MCP tools.
2. **For General Investors (Phase 3 & 4)**: A dual-pane Web App & Copilot Canvas where non-technical users define capital, risk appetite, and goals to discover, backtest, and deploy curated strategies in one click.

---

## 📂 Project Structure

```text
quant-copilot/
├── docs/
│   ├── MASTER_ARCHITECTURE.md   <-- Core blueprint & tech specs
│   ├── PROJECT_STATUS.md        <-- Living state & milestone tracker
│   └── API_CONTRACTS.md         <-- Schemas for Strategy DSL & MCP
├── src/
│   ├── schema/                  <-- Pydantic definitions (Strategy DSL, Trades)
│   ├── engine/                  <-- Deterministic Backtest & Analysis engine
│   ├── brokers/                 <-- Abstract BaseBroker, PaperBroker, DhanClient
│   ├── risk/                    <-- Risk Sentinel (Kill-switch, Drawdown guards)
│   └── mcp/                     <-- Model Context Protocol tool endpoints
├── tests/                       <-- Unit & integration tests
├── config/                      <-- Market settings & credentials template
└── README.md                    <-- Getting started & system overview
```

---

## 🗺️ Roadmap & Phase Progression

- [ ] **Phase 1: The Quant & Execution Engine (Personal MVP)**
  - Canonical Strategy Schema (Declarative JSON/Pydantic)
  - Deterministic Backtester (Out-of-sample testing, slippage, brokerage)
  - Paper Trading Simulator & WebSocket market tick consumer
  - Broker Adapter for Indian Markets (DhanHQ & PaperBroker)
  - Risk Sentinel & Emergency Kill-switch
- [ ] **Phase 2: Modular Skills & MCP Server**
  - MCP Tool: `strategy_formulate`
  - MCP Tool: `strategy_backtest`
  - MCP Tool: `strategy_deploy`
  - MCP Tool: `strategy_status` & `strategy_stop`
- [ ] **Phase 3: The Full Product & Copilot UI Platform**
  - Full-stack Web Application (Next.js/React + Fast API / Node.js)
  - Dual-Pane UI: Conversational Copilot (Left) + Interactive Visual Canvas (Right)
  - Interactive Equity Curves, Drawdown Waterfalls, Live Trade Log
  - Deployment Cockpit with Live/Paper switch and kill-switch button
- [ ] **Phase 4: Investor Marketplace & Recommender (Phase 2.0)**
  - Strategy Registry & Scoring Engine
  - Investor Profiler & Portfolio Allocator
  - Public Marketplace & Remote MCP integration

---

## 🔄 Token & Context Preservation Guide
To resume work in any new chat window with minimal token consumption:
1. Simply prompt: *"Read `docs/PROJECT_STATUS.md` in `quant-copilot` and resume where we left off."*
2. The agent only reads `PROJECT_STATUS.md` (a lightweight file) instead of burning tokens reprocessing chat history.
