# Lesson 1: The Strategy DSL (Domain Specific Language)

**Module:** `src/schema/strategy.py`

When building AI-driven quantitative trading systems, one of the most critical design decisions is how the AI generates and stores trading strategies. 

## 1. WHAT is the Strategy DSL?
At its core, a DSL (Domain Specific Language) acts as a **rigid blueprint or contract**. 

Instead of letting the AI write arbitrary code (like `buy_option(...)`), we provide a highly specific, fill-in-the-blanks form. This form defines exactly:
* What time do we enter?
* Do we buy or sell?
* Call or Put?
* What is the Stop Loss?
* When do we shut down for the day?

`strategy.py` is the digital version of this form, built using **Pydantic** (a Python data validation library). Any trading strategy that wants to run on our platform *must* perfectly fit into this pre-defined schema.

---

## 2. WHY a Declarative Schema instead of Raw Python Code?

If you ask an LLM to "create a trading strategy", its default behavior is to output raw, executable Python code. Allowing an AI to write and execute raw code in a live trading system is extremely dangerous for three primary reasons:

1. **Hallucination & Crashes:** The AI might invent a function that doesn't exist or pass the wrong data type (e.g., passing a string instead of a float). A single syntax error can crash the live execution loop while real money is on the line.
2. **Lookahead Bias:** In backtesting, the AI might accidentally write code that "peeks" into future data (e.g., `current_price = df['close'].iloc[i + 1]`). This creates a fake, wildly profitable backtest that will fail in the real market.
3. **No UI Interoperability:** If a user generates a strategy, we want to display it on a beautiful Web UI as a visual flowchart or via sliders and buttons. You cannot easily parse raw, arbitrary Python code back into visual UI components.

**The Solution:**
By using Pydantic, we force the AI to output **structured JSON**, not code. 
Because it is just data, we can:
* Render it easily on a React frontend.
* Validate every single field *before* we risk money.
* Feed it into a deterministic backtester that *we* control, guaranteeing no lookahead bias.

---

## 3. HOW does it work? (Code Breakdown)

Let's look at how `strategy.py` is structured, from the smallest pieces to the largest:

### Step A: The Enums (The Multiple Choice Questions)
We define strict choices like `InstrumentType` (`EQUITY`, `CE`, `PE`) and `OrderAction` (`BUY`, `SELL`). 
Think of Enums as dropdown menus. We don't let the AI type whatever it wants; it *must* pick from the dropdown. This prevents the AI from typing `"Call"` instead of `"CE"`.

### Step B: The Condition Tree (The Rules)
To tell the computer *"If RSI is less than 30 AND the time is after 9:20 AM"*, we break it into an **Abstract Syntax Tree (AST)**:
* **`Operand`**: The thing we are looking at (e.g., "RSI", "30", "time", "09:20").
* **`ConditionNode`**: A single rule (e.g., `RSI < 30`).
* **`ConditionGroup`**: Gluing rules together (e.g., Rule 1 `AND` Rule 2).

### Step C: The Leg (The Trade)
A `Leg` is a single transaction. For example, a "Straddle" consists of two legs (Selling a Call and Selling a Put).
We use Pydantic's `@model_validator` to enforce strict logical rules:
```python
@model_validator(mode='after')
def validate_options_fields(self) -> 'Leg':
    # If the user/AI selects a Call or Put, they absolutely MUST provide a Strike Price and Expiry.
```
If the AI forgets the expiry date for an option, Pydantic immediately throws an error.

### Step D: Deployment Settings (The Brakes)
This enforces institutional risk management:
* **`max_daily_loss`**: The circuit breaker. If the account loses this amount, trading is locked for the day. (Prevents revenge trading).
* **`limit_buffer_pct`**: In Indian markets, algorithmic Market orders can face huge slippage. We force the system to use "Limit Buffer" orders (e.g., placing a limit order 0.5% above the market price to guarantee a fill safely).

### Step E: The Strategy Definition (The Binder)
This is the root object (`StrategyDefinition`). It holds everything together: the Name, the Underlying asset (like NIFTY), the Sets (rules and legs), and the Deployment Settings.

---

## 4. The Self-Correcting AI Loop
When the Copilot AI generates a strategy, it outputs JSON. `strategy.py` takes that JSON and checks every field. 
If the AI makes a mistake (e.g. forgets a required field), `strategy.py` rejects it. We can then automatically feed that exact error back to the AI, allowing it to fix its own mistake before it ever reaches the live market.
