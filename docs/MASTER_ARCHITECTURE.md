# Master Architecture & Technical Specification

> **Document Version**: 1.1.0  
> **Target Market**: Indian Equities & Derivatives (NSE/MCX) via Fyers API v3 / Angel One SmartAPI / Paper Broker  
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
|                                   ├── FyersBroker (Fyers API v3 - Execution)      |
|                                   ├── AngelBroker (Angel One SmartAPI)            |
|                                   └── [Optional] DhanClient / ZerodhaClient       |
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
* **Data Ingestion**: Historical 1-minute/15-minute/daily OHLCV candles fetched via Angel One SmartAPI (10+ yr depth), Fyers API v3, or local compressed Parquet cache (`SmartCacheManager`).
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

### Module D: The Lean Risk Sentinel (Account Airbag & Master Kill-Switch)
To keep strategy logic completely decoupled and autonomous, all trade-specific rules (cooldowns, indicators, trailing stops, strategy-level exits) live strictly inside the individual strategies. The Sentinel acts exclusively as the **Account-Level Emergency Airbag**:
1. **Master Emergency Kill-Switch (`kill_all()` / `/kill`)**: Atomic panic command that cancels all open orders on the broker, flattens all open positions across the entire account at market price, and disconnects the runner.
2. **Automated Loss Airbag (`max_daily_loss` tripwire)**: Configurable threshold (INR or % of margin, e.g. ₹3,500 / 5% on MCX Aluminium Mini Lot). Automatically trips the Master Kill-Switch if total account daily loss breaches this limit while the user is away from screen.
3. **Session Latch & Morning Auto-Reset**: Locks trading for the remainder of today's session to prevent revenge bleeding; resets automatically at 08:30 AM next morning for the new trading day (with manual CLI/Telegram `--unlock` override).

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
* **`PaperBroker`**: Runs locally with a virtual wallet (e.g., starting with ₹1,00,000), simulating realistic fills, slippage, and PnL on real incoming live ticks or 15m candle closes.
* **`FyersBroker`**: Primary live execution client via `fyers_apiv3` SDK. Features sub-50ms order routing, native Market Price Protection (MPP), dedicated WebSocket Order/Trade Sockets for instant fill callbacks, and automated headless TOTP authentication.
* **`AngelBroker`**: Secondary live client and primary deep market data engine via `smartapi-python` (10+ year 15m/1m history, free WebSocket ticks).
* **Cloud VPS Architecture (Always-On 24/7)**:
  * Deployed on low-cost Linux cloud VPS (**Vultr Mumbai ~₹300–₹600/mo** or AWS Mumbai with Elastic IP).
  * Whitelisted public **Static IPv4** required by SEBI/exchange regulations for automated order execution.
  * Headless service managed by `systemd` daemon with automatic crash recovery and Telegram push alerts.

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
