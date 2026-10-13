# Benchmark Strategy: Nestle India 200 SMA Strategy

> **Status**: Official Golden Integration Benchmark Strategy  
> **Source Platform**: Tradetron (Strategy ID: `10038358`)  
> **Role in QuantCopilot**: Used as the definitive end-to-end integration and backtest validation target for the platform.

---

## 1. Specification Overview

| Parameter | Specification |
| :--- | :--- |
| **Strategy Name** | Nestle India SMA 200 |
| **Strategy ID** | 10038358 (Tradetron) |
| **Underlying Asset** | `NSE:NESTLEIND` (Nestle India Stock Futures) |
| **Timeframe** | 15-Minute Candles (`15m`) |
| **Primary Indicator** | 200 Simple Moving Average (SMA) on 15m Close |
| **Execution Style** | Positional Trend Following |
| **Rollover Mode** | Coordinated Dual-Contract Handover (No artificial rollover orders) |

---

## 2. Executive Summary & Core Mechanics

The **Nestle India SMA 200** strategy is an automated trend-following system designed specifically for **NSE Stock Futures**. It captures sustained momentum by:
- **Long Entry**: Price trades above 200 SMA on 15-minute candles.
- **Short Entry**: Price trades below 200 SMA on 15-minute candles.

### Coordinated Dual-Contract Handover
Unlike cash equities, Indian stock futures expire on the last Thursday of every month and carry mandatory physical delivery if held to settlement (with exponential margin spikes in expiry week). 

To eliminate delivery risk and avoid illiquidity, the strategy operates a dual-contract handover:
1. **Current Month Phase ($> 6$ Days to Expiry)**: Trades exclusively in the near-month contract.
2. **Next Month Phase ($\le 6$ Days to Expiry)**: Automatically shifts all new trades to the next-month contract.
3. **Flat Position Safety Guard**: Enforces a single active position rule (`OPEN_POSITIONS == 0`) so next-month trades never enter while a current-month position is still open.
4. **Pre-Expiry Safety Net**: Automatically closes any open current-month position **1 day before expiry** to eliminate physical delivery and settlement risk.

---

## 3. Operational Transition Timeline (Example)

Consider a transition between October and November contracts:

```
[Oct 20] 10 Days to Expiry:
         Current month SMA turns bullish 
         --> Set 1 enters BUY October NESTLEIND Futures.

[Oct 24] 6 Days to Expiry (Handover Boundary):
         Handover threshold reached, but October trade is still active.
         --> Next-month Sets (3 & 4) remain blocked by (OPEN_POSITIONS == 0) guard.

[Oct 29] 1 Day to Expiry (Pre-Expiry Safety Net):
         Days to Expiry <= 1 triggers
         --> Set 1 forces EXIT on October contract (avoids physical delivery).
         --> Account is now FLAT.

[Oct 29] Post-Exit Evaluation:
         Account is now flat. If November contract is bullish on 200 SMA
         --> Set 3 enters BUY November NESTLEIND Futures.

[Nov 01] New Month Begins:
         November contract physically becomes active near-month.
         --> Position continues riding the trend without artificial rollover gaps.
```

---

## 4. Platform Engine Capabilities Tested by This Benchmark

When we run our end-to-end integration test against this strategy, the engine must prove:
1. **Multi-Timeframe Resampling**: Accurately resampling raw 1-minute historical data into 15-minute OHLCV candles.
2. **High-Period Indicator Math**: Correctly computing 200 SMA on 15m intervals without lookahead bias.
3. **NSE F&O Expiry Awareness**: Calculating dynamic Days to Expiry (DTE) for NSE equity derivative monthly expiry calendars.
4. **Multi-Set Coordination & Guards**: Evaluating multi-set conditions respecting account position states (`OPEN_POSITIONS == 0`).
5. **Contract Lifecycle Management**: Mapping `MONTHLY` vs `FAR_MONTH` futures contracts dynamically.
