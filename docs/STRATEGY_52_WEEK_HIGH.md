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

## 4. Key Architectural Lessons from 52-Week Low Strategy

> [!IMPORTANT]
> **Key Architectural Pattern to Reuse from 52-Week Low Strategy**:
> During the implementation of the 52-Week Low Strategy, two fundamental lessons were learned that **must** be applied directly to the 52-Week High Strategy:
>
> 1. **Local Institutional Discovery Base (`config/nifty500.csv` & `config/nifty200.csv`)**:
>    - **Never rely solely on external daily web scrapers (like NSE "top gainers")**.
>    - Strong compounders frequently break out into 52-week highs steadily (+1.5% to +3.0%) without appearing in the volatile "Top 20 Percentage Gainers" list.
>    - The 52W High scanner **must scan the curated local Nifty 500 universe** directly using `SmartCacheManager` so zero quality leaders are missed.
>
> 2. **Multi-Session Breakout & Retest Lookback (T-5 Day Window)**:
>    - Just like capitulation, **breakouts are rarely isolated to a single day**.
>    - A stock may have its $5\times$ volume breakout on Day 1, and on Day 3–5 it may test the breakout level on lower volume (pullback/retest).
>    - The technical engine must evaluate a rolling **5-day lookback window** for maximum volume expansion and breakout level retests, rather than evaluating only the current day's single bar in isolation.

---

## 5. Implementation Schedule
Implementation will follow the completion of the 52-Week Low Capitulation Strategy (Phases B, C, D).

