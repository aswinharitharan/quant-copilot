# Master Architecture & Technical Specification

> **Document Version**: 1.0.0  
> **Target Market**: Indian Equities & Derivatives (NSE/BSE) via DhanHQ / Paper Broker  
> **System Architecture**: Event-Driven, Decoupled Engine, MCP-Exposed, Dual-Pane Web UI  

---

## 1. System Topology

```
+-----------------------------------------------------------------------------------+
|                            USER EXPERIENCE LAYER                                   |
|  [ Pro / Creator Mode: Strategy Studio ]    [ Investor Mode: Smart Marketplace ] |
|  Dual-Pane: Chat Copilot (Left) <-------> Dynamic Trading Canvas / Cockpit (Right)|
+-----------------------------------------▲-----------------------------------------+
                                          │ REST / SSE / WebSockets
+-----------------------------------------▼-----------------------------------------+
|                              ORCHESTRATION LAYER                                  |
|         FastAPI / Node Server <---> LLM (Gemini / Anthropic / Local Agent)        |
+-----------------------------------------▲-----------------------------------------+
                                          │ Model Context Protocol (MCP)
+-----------------------------------------▼-----------------------------------------+
|                             MCP SERVICE LAYER                                     |
|  tools: formulate | backtest | deploy_paper | deploy_live | monitor | emergency_stop |
+-----------------------------------------▲-----------------------------------------+
                                          │ Python Core APIs
+-----------------------------------------▼-----------------------------------------+
|                             CORE ENGINE LAYER                                     |
|  ┌─────────────────────┐  ┌──────────────────────┐  ┌──────────────────────────┐  |
|  │ Strategy DSL Engine │  │ Backtest Engine      │  │ Risk Sentinel (Guardian) │  |
|  │ (Pydantic Schema)   │  │ (Costs, Slippage)    │  │ (Daily Loss, Kill-Switch)│  |
|  └─────────────────────┘  └──────────────────────┘  └──────────────────────────┘  |
+-----------------------------------------▲-----------------------------------------+
                                          │ Internal Abstract Interface
+-----------------------------------------▼-----------------------------------------+
|                             BROKER ADAPTER LAYER                                  |
|         BaseBroker (Interface) <──┬── PaperBroker (Local Simulation)              |
|                                   ├── DhanClient (DhanHQ API)                     |
|                                   └── [Future] ZerodhaClient / AngelOneClient     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Modules Breakdown

### Module A: Strategy DSL (Domain Specific Language)
To prevent LLM hallucination and fatal syntax errors during live execution, strategies are represented as **declarative Pydantic schemas**:
* **Universe**: Exchange, Symbol, Instrument Type (EQUITY, FUTURES, OPTIONS), Resolution (1m, 5m, 15m, 1D).
* **Indicators**: Parameterized technical or price-action indicators (e.g. `EMA(period=20)`, `VWAP()`, `RSI(period=14)`).
* **Triggers**: Explicit boolean logic trees (`crosses_above`, `greater_than`, `touches_band`).
* **Risk & Sizing**: Position sizing mode (`fixed_qty`, `percent_equity`, `risk_per_trade`), Stop Loss %, Trailing Stop %, Target %.
* **Session & Execution**: Intraday auto-exit time (e.g., 15:15 IST), max trades per day, order type (`MARKET`, `LIMIT`).

### Module B: The Deterministic Backtester
* **Data Ingestion**: Historical 1-minute/daily OHLCV candles fetched via DhanHQ API or local Parquet cache.
* **Realistic Friction Modeling**:
  * Exchange Turnover Charges & STT (Securities Transaction Tax)
  * Brokerage calculations
  * Slippage simulation (0.05% to 0.1% baseline for liquid instruments)
* **Metrics Suite**:
  * Total Return, CAGR, Annualized Volatility
  * Sharpe Ratio, Sortino Ratio, Calmar Ratio
  * Max Drawdown (%) and Max Drawdown Duration
  * Win Rate (%), Profit Factor, Expectancy per trade

### Module C: The Deployment Handshake Protocol
Before any strategy transitions from Backtested to Deployed (Paper or Live), the AI executes a structured conversational handshake:
1. **Expiry Rollover Protocol**: Choice of auto-rollover into the next contract (e.g. 1 day before expiry at 14:30 IST) vs square-off.
2. **Capital & Sizing**: Explicit capital allocation limit (e.g. ₹1,00,000) and Lot sizing mode (fixed vs equity scaled).
3. **Account Circuit Breaker (Max Daily Loss)**: Mandatory cutoff where all positions are flattened and runner locks for the day.
4. **Overtrading Ratchet**: Strict daily re-entry limit (e.g. max 2-3 round trips) to avoid whipsaws.
5. **Smart Execution Buffer**: Immediate-Fill Limit orders (0.5%-1% buffer) adhering to Indian exchange rules on NSE/MCX.
6. **Market Open Buffer**: First trade condition check delayed to 09:20 IST to avoid 09:15 AM opening spread anomalies.

### Module D: The Risk Sentinel (The Uncompromising Guardian)
Before any order reaches the broker or paper trade book, it passes through the Sentinel:
1. **Max Daily Loss Limit**: If current day realized + unrealized PnL drops below `-X%` or `-₹Y`, all active positions are squared off and trading is locked for the remainder of the session.
2. **Max Position Limit**: Caps total capital exposure.
3. **Hard Emergency Kill-Switch**: A single atomic command/button that cancels open orders, closes active positions at market price, and disconnects the runner.

### Module D: Broker Adapter Architecture
Abstract base class:
```python
class BaseBroker(ABC):
    @abstractmethod
    async def get_balance(self) -> float: ...
    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse: ...
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    async def get_positions(self) -> list[Position]: ...
    @abstractmethod
    async def subscribe_ticks(self, symbols: list[str], callback) -> None: ...
```
* **`PaperBroker`**: Runs locally with a virtual wallet (e.g., starting with ₹1,00,000), simulating realistic fills on real incoming live ticks.
* **`DhanClient`**: Implemented using `dhanhq` Python SDK for zero-cost live orders and live tick WebSocket streams.

---

## 3. Product & UI Specifications (Phase 3)

### Dual-Pane Copilot Canvas Layout
* **Left Pane (Conversational AI)**:
  * Natural language strategy ideation, automated critique, parameter probing.
  * Direct execution requests (*"Backtest on BankNifty for the last 6 months"*, *"Switch to paper trade"*).
* **Right Pane (Live Canvas)**:
  * **Top**: Strategy Card (Visual indicator flowchart + parameters).
  * **Middle**: Interactive Chart (Equity Curve, Benchmark Comparison, Drawdown chart).
  * **Bottom**: Active Execution Cockpit (Running status, Open PnL, Live order ticks, Emergency Kill-Switch button).

---

## 4. Phase 2.0 Consumer Marketplace & Recommendation Engine
* **Strategy Registry**: Database storing every validated strategy with historical metrics, risk ratings, and minimum capital requirements.
* **Investor Profiler**: Collects user capital, risk tolerance, and time horizon.
* **Matching Algorithm**: Multi-objective optimization matching investors to non-correlated strategy combinations while strictly bounding maximum historical drawdown.
