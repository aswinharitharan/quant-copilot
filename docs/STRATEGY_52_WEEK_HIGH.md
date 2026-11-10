# 52-Week High Dual-Mode Strategy (Breakout vs. Exhaustion Climax)

> **Status**: ⏳ Pending / Roadmapped (Scheduled after 52-Week Low implementation)  
> **Target Market**: Indian Equities & F&O (NSE)  
> **Strategy Type**: Momentum Continuation / Exhaustion Top Reversal  
> **Authoring Lead**: QuantCopilot AI  
> **Master Roadmap**: [PROJECT_STATUS.md](file:///Users/aswinkarthik.th/.gemini/antigravity-ide/scratch/quant-copilot/docs/PROJECT_STATUS.md)

---

## 1. Dual-Mode Framework Overview

Stocks hitting 52-week highs on abnormal volume are categorized by candle closure and market structure:

```
                       52-WEEK HIGH HIT WITH VOLUME SPIKE
                                       │
        ┌──────────────────────────────┴──────────────────────────────┐
        ▼                                                             ▼
[ Scenario 1: Clean Close at High ]                   [ Scenario 2: Severe Rejection at High ]
- Close in top 20% of candle range                    - Long upper wick (> 50% of range)
- From a 4-8 week consolidation                       - Parabolic run already (> 40% in 1 month)
- Strong fundamentals (Sales/Profit > 15%)            - Closes in bottom 40% of range
        │                                                             │
        ▼                                                             ▼
TACTIC 1: MOMENTUM BREAKOUT / RETEST                  TACTIC 2: EXHAUSTION CLIMAX
(Buy to ride multi-month trend)                       (Profit booking on delivery / Short in F&O)
```

---

## 2. Tactic 1: Momentum Continuation Breakout (Long)
- **Base Requirement**: Emerges from a 3 to 8 week consolidation base (not vertically overextended).
- **Candle Requirement**: Closes in the **top 20%** of the day's high-low range with minimal upper shadow.
- **Volume**: $\ge 2.5\times$ to $5\times$ 20-day average volume.
- **Stop-Loss**: Low of breakout day or $-6\%$ to $-8\%$.
- **Trailing Rule**: Daily 20 EMA trail.

---

## 3. Tactic 2: Exhaustion Climax / UTAD (Short / Profit-Taking)
- **Context**: Parabolic run already underway ($> 30\%$ above 50 EMA without basing).
- **Candle Rejection**: Upper shadow $\ge 50\%$ of total range, or closes in lower 40% of range on $5\times - 15\times$ volume.
- **Action**:
  - Delivery holdings: **100% Exit / Book Profit**.
  - F&O stocks: Short entry on breakdown below climax candle low with tight SL above the high.

---

## 4. Implementation Schedule
Implementation will follow the completion of the 52-Week Low Capitulation Strategy (Phases B, C, D).

