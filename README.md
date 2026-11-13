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
├── learning/                    <-- Educational breakdowns of code and quant architecture
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

---

## 📡 Public API Reference (`UnifiedScannerService`, `ScannerService` & `HighScannerService`)

The unified orchestrator and strategy service facades (`src/scanner/unified_service.py`, `src/scanner/service.py` & `src/scanner/high_service.py`) provide the core interfaces for QuantCopilot:

### Unified 52-Week Strategy Orchestrator (`UnifiedScannerService`)

Trigger phrase: **"whats today for 52"** — executes both strategies concurrently and produces a unified executive briefing.

```bash
# Run unified evening dashboard for both strategies (High Breakout + Low Capitulation)
python scripts/run_52_scanner.py daily

# Run specific strategy only
python scripts/run_52_scanner.py daily --strategy high
python scripts/run_52_scanner.py daily --strategy low
```

| Method | Signature | Description |
| :--- | :--- | :--- |
| `get_unified_daily_briefing` | `(candidate_symbols=None, as_of_date=None, strategy="both", skip_fundamental_audit=False) -> Dict[str, Any]` | Concurrently runs both strategies and aggregates results into a combined payload. |
| `format_unified_briefing_markdown` | `(briefing: Dict[str, Any]) -> str` | Formats both strategy dashboards, active holdings, and deduplicated promoter insider trades into an executive report. |

### 52-Week Low Strategy (`ScannerService`)

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

### 52-Week High Breakout Strategy (`HighScannerService`)

| Method | Signature | Description |
| :--- | :--- | :--- |
| `get_daily_briefing` | `(candidate_symbols=None, as_of_date=None, skip_fundamental_audit=False, current_prices_and_emas=None) -> DailyDashboard52High` | Full evening executive briefing ('Whats today for 52 High') with 4-layer breakout funnel and trailing stop sentinels. |
| `format_daily_briefing_markdown` | `(dashboard: DailyDashboard52High) -> str` | Formats the 52W-High briefing payload into an executive Markdown report. |
| `scan_radar_candidates` | `(candidate_symbols=None, as_of_date=None) -> Tuple[List[BreakoutSignal], str]` | Scans Nifty 500 candidate universe for sound 52W high breakouts from VCP consolidation bases. |
| `get_portfolio_summary` | `(current_prices_and_emas=None, as_of_date=None) -> Tuple[List[HighPortfolioStock], str]` | Checks active breakout positions against dynamic trailing 20 EMA ratchet and target levels (+15%, +30%). |
| `get_watchlist_summary` | `(as_of_date=None) -> Tuple[List[HighWatchlistStock], str]` | Reviews Tier 1 breakout watchlist for Stage 2 confirmation triggers (close above breakout pivot high). |
| `audit_single_symbol` | `(symbol: str, df=None) -> Dict[str, Any]` | Deep audit of single symbol: base depth %, ATR contraction ratio, 200 SMA slope, growth fundamentals. |
| `record_buy` | `(symbol, entry_price, quantity, entry_date=None, notes=None) -> HighPortfolioStock` | Logs position buy into Tier 2 portfolio with initial SL and trailing 20 EMA ratchet floor. |
| `record_sell` | `(symbol, sell_price, quantity, reason, sell_date=None, notes=None) -> Tuple[HighPortfolioStock, Optional[ClosedTradeLedger]]` | Logs partial profit taking (e.g. 50% at T1) and archives completed trades to Tier 3 Ledger. |

> **Note on Internal Helpers**:  
> Methods such as `add_to_watchlist` and `remove_from_watchlist` are convenience helpers wrapping `PortfolioTracker` / `HighPortfolioTracker`. They facilitate CLI operations and internal copilot shortcuts, but are **not** exposed in the public Model Context Protocol (MCP) server schema.

> **Note on Internal Helpers**:  
> Methods such as `add_to_watchlist` and `remove_from_watchlist` are convenience helpers wrapping `PortfolioTracker`. They facilitate CLI operations and internal copilot shortcuts, but are **not** exposed in the public Model Context Protocol (MCP) server schema.

