# Benchmark Strategy: Nestle India 200 SMA Strategy

> **Status**: Official Golden Integration Benchmark Strategy  
> **Source Platform**: Tradetron (Strategy ID: `10038358`)  
> **Implementation**: `src/strategies/nestle_200_sma.py`  
> **Role in QuantCopilot**: The definitive end-to-end integration and backtest validation target for the platform.

---

## 1. Specification Overview

| Parameter | Specification |
| :--- | :--- |
| **Strategy Name** | Nestle India SMA 200 Futures Benchmark |
| **Strategy ID** | `10038358` (Tradetron) |
| **Signal Instrument** | `NSE:NESTLEIND` (Continuous Stock / Spot Equity Candles) |
| **Traded Instrument** | `NSE_FNO:NESTLEIND` (Stock Futures, 1 Lot = 25 Shares) |
| **Timeframe** | 15-Minute Candles (`15m`) |
| **Primary Indicator** | 200 Simple Moving Average (SMA) on 15m Close |
| **Signal Timing** | `SignalTiming.PREVIOUS_BAR_CLOSE` (Evaluated on closed candle $t-1$, executed at Open of candle $t$) |
| **Market Open Delay** | `0 Minutes` (Enables prompt 09:15 AM market open execution for overnight signals) |
| **Execution Style** | Positional Trend Following / Stop-and-Reverse (SAR) |
| **Max Concurrent Positions** | `1` (`OPEN_POSITIONS == 0` concurrency guard across all 4 sets) |
| **Rollover Mode** | Coordinated Dual-Contract Handover (No artificial rollover orders) |
| **Capital Allocation** | ₹5,00,000 (Margin buffer for 1 lot futures) |

---

## 2. Executive Summary & Core Mechanics

The **Nestle India SMA 200** strategy is an automated trend-following and stop-and-reverse system designed for **NSE Stock Futures**. It uses the continuous underlying cash stock price for clean indicator calculations while executing futures contracts for capital efficiency.

### Core Signal Rules (Candle Body & Wick Clearance)
To prevent whipsaw losses from intraday spikes that temporarily breach the moving average without establishing momentum, entry and exit conditions require **full candle body and wick clearance**:

1. **Long Entry Signal**:
   - `Close > 200 SMA` **AND** `Low > 200 SMA`
   - *Rationale*: Both the candle close and the lower wick must trade entirely above the 200 SMA.
2. **Short Entry Signal**:
   - `Close < 200 SMA` **AND** `High < 200 SMA`
   - *Rationale*: Both the candle close and the upper wick must trade entirely below the 200 SMA.
3. **Long Exit Signal**:
   - `Close < 200 SMA` **AND** `High < 200 SMA` (or `DTE <= 1` for near-month physical delivery protection).
   - Symmetrical to the Short Entry condition.
4. **Short Exit Signal**:
   - `Close > 200 SMA` **AND** `Low > 200 SMA` (or `DTE <= 1` for near-month physical delivery protection).
   - Symmetrical to the Long Entry condition.

---

## 3. Coordinated Dual-Contract Handover Architecture

Indian stock futures expire on the last Thursday of each month and require mandatory physical delivery if held past expiry. The strategy eliminates delivery risks and rollover execution friction using a 4-Set coordinated structure:

### Strategy Set Breakdown

| Set ID | Name | Trigger Condition (Signal on $t-1$) | Instrument Traded | Exit Conditions |
| :---: | :--- | :--- | :--- | :--- |
| **Set 1** | Near-Month Long | `DTE > 6` AND `Close > 200 SMA` AND `Low > 200 SMA` | Current Month Futures (BUY) | (`Close < SMA` AND `High < SMA`) OR `DTE <= 1` |
| **Set 2** | Near-Month Short | `DTE > 6` AND `Close < 200 SMA` AND `High < 200 SMA` | Current Month Futures (SELL) | (`Close > SMA` AND `Low > SMA`) OR `DTE <= 1` |
| **Set 3** | Next-Month Long | `DTE <= 6` AND `Close > 200 SMA` AND `Low > 200 SMA` | Next Month Futures (BUY) | `Close < SMA` AND `High < SMA` |
| **Set 4** | Next-Month Short | `DTE <= 6` AND `Close < 200 SMA` AND `High < 200 SMA` | Next Month Futures (SELL) | `Close > SMA` AND `Low > SMA` |

### Key Operational Invariants
1. **Single Position Guard (`OPEN_POSITIONS == 0`)**:
   - Only 1 position can be active across Sets 1, 2, 3, and 4 at any time.
   - When DTE drops $\le 6$, next-month sets (3 & 4) do not enter until the active near-month trade completes its exit.
2. **Pre-Expiry Physical Delivery Safety Net (`DTE <= 1`)**:
   - Sets 1 and 2 automatically exit if still held 1 day prior to monthly expiry, avoiding margin surges and physical settlement.
3. **Execution Order on Bar $t$**:
   - Exits are evaluated and filled first at `bar.open`.
   - The position counter drops to `0`.
   - The opposite reversal entry condition evaluates and fills immediately at the same `bar.open`.

### Operational Transition Timeline (Example)

Consider a transition between October and November contracts:

```
[Oct 20] 10 Days to Expiry:
         Current month SMA turns bullish (Close > 200 SMA and Low > 200 SMA)
         --> Set 1 enters BUY October NESTLEIND Futures.

[Oct 24] 6 Days to Expiry (Handover Boundary):
         Handover threshold reached (DTE <= 6), but October trade is still active.
         --> Next-month Sets (3 & 4) remain blocked by (OPEN_POSITIONS == 0) single-position guard.

[Oct 29] 1 Day to Expiry (Pre-Expiry Safety Net):
         Days to Expiry <= 1 triggers
         --> Set 1 forces EXIT on October contract (avoids physical delivery & margin penalties).
         --> Account is now FLAT (OPEN_POSITIONS == 0).

[Oct 29] Post-Exit Evaluation:
         Account is now flat. If market remains bullish on 200 SMA (Close > 200 SMA & Low > 200 SMA)
         --> Set 3 enters BUY November NESTLEIND Futures on the next bar open.

[Nov 01] New Month Begins:
         November contract physically becomes the active near-month contract.
         --> Position continues riding the trend without artificial rollover orders or double transaction friction.
```

---

## 4. Signal Timing & Data Architecture

### Signal Timing: `SignalTiming.PREVIOUS_BAR_CLOSE`
- **Signal Generation ($t-1$)**: Indicators and conditions are evaluated on the closed 15-minute candle.
- **Execution ($t$)**: Orders are filled at the `open` price of the current candle.
- **Market Open Gate (`market_open_delay_minutes = 0`)**: Overnight signals generated by the 15:15–15:30 candle are filled immediately at 09:15:00 market open, ensuring zero-gap continuous reversal.

### Spot Candle for Signals vs. Futures for Execution
- **Signals**: Evaluated against continuous spot equity (`NESTLEIND.NS` / `NSE_EQ`) to guarantee 5+ years of continuous indicator memory free from futures rollover basis distortion.
- **Execution**: Filled in `NSE_FNO` futures with 1 lot = 25 shares.
- **Cost Model**: NSE Futures regulatory costs applied:
  - STT: 0.02% on sell side turnover
  - Exchange transaction charges: 0.002%
  - SEBI turnover fee: 0.0001%
  - Stamp duty: 0.002% on buy side
  - GST: 18% on transaction charges
  - Slippage buffer: 0.05%

---

## 5. Verified Empirical Backtest Results (60 Days / 15m)

Tested on 60 days of real 15-minute candles from Yahoo Finance (`NESTLEIND.NS`):

| Metric | Value |
| :--- | :--- |
| **Test Period** | 2026-08-31 to 2026-10-26 (945 candles) |
| **Initial Capital** | ₹5,00,000.00 |
| **Final Equity** | ₹5,00,977.26 |
| **Net PnL** | **+₹977.26** (+0.20%) |
| **Profit Factor** | **1.27** |
| **Total Completed Trades** | **13** |
| **Trade Continuum** | 100% continuous Stop-and-Reverse (every exit immediately reversed) |
| **Total Transaction Friction** | ₹552.74 |
| **Max Drawdown** | 0.96% (20 days) |

### Sample Trade Execution Chain

```
Trade 1 (Set 2 Short) : In 2026-09-10 09:30 @ ₹1,394.50  -->  Out 2026-09-22 09:15 @ ₹1,382.40 (+₹258.42 net)
Trade 2 (Set 3 Long)  : In 2026-09-22 09:15 @ ₹1,382.40  -->  Out 2026-09-22 10:00 @ ₹1,378.50 (-₹141.29 net)
Trade 3 (Set 4 Short) : In 2026-09-22 10:00 @ ₹1,378.50  -->  Out 2026-09-23 11:00 @ ₹1,382.40 (-₹141.29 net)
Trade 4 (Set 3 Long)  : In 2026-09-23 11:00 @ ₹1,382.40  -->  Out 2026-09-24 10:00 @ ₹1,372.90 (-₹281.19 net)
Trade 5 (Set 4 Short) : In 2026-09-24 10:00 @ ₹1,372.90  -->  Out 2026-10-06 15:15 @ ₹1,338.50 (+₹816.91 net)
```

---

## 6. Regression Test Suite
Automated unit tests validating these rules reside in [`tests/test_benchmark_nestle.py`](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/tests/test_benchmark_nestle.py):
- `test_nestle_benchmark_schema_validity`: Schema parameters, lot sizing, and execution style.
- `test_low_wick_filter_blocks_long_entry`: Verifies long entries require `Low > SMA`.
- `test_high_wick_filter_blocks_short_entry`: Verifies short entries require `High < SMA`.
- `test_single_position_guard_blocks_concurrent_trades`: Confirms strict 1-position concurrency.
- `test_previous_candle_signal_fills_on_current_candle_open`: Confirms candle $t-1$ signals fill at candle $t$ open.
- `test_high_wick_filter_blocks_long_exit`: Verifies long exits require upper wick clearance (`High < SMA`).
- `test_low_wick_filter_blocks_short_exit`: Verifies short exits require lower wick clearance (`Low > SMA`).
