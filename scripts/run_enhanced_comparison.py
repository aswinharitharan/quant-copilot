"""
Head-to-Head Benchmark Runner:
Original 200 SMA vs Enhanced 200 SMA (ATR Dead-Zone + ADX Gate + Cooldown + Target/SL)
Evaluated across NESTLEIND, HINDUNILVR, and ALKEM.
"""

import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar
from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.strategies.nestle_200_sma_enhanced import get_nestle_200_sma_enhanced_strategy
from src.strategies.hindunilvr_200_sma import get_hindunilvr_200_sma_strategy
from src.strategies.hindunilvr_200_sma_enhanced import get_hindunilvr_200_sma_enhanced_strategy
from src.strategies.alkem_200_sma import get_alkem_200_sma_strategy
from src.strategies.alkem_200_sma_enhanced import get_alkem_200_sma_enhanced_strategy


def main():
    print("=" * 105)
    print(" 🚀 QuantCopilot Strategy Benchmark: Original 200 SMA vs Enhanced 200 SMA")
    print("=" * 105)

    cal = ExpiryCalendar()
    cost_model = TransactionCostModel(brokerage_per_order=0.0, futures_slippage_pct=0.0005)

    stocks = [
        {
            "symbol": "NESTLEIND",
            "cache": "data/cache/NESTLEIND_NSE_15m_2022-01-03_2026-09-30.parquet",
            "start": "2022-01-03",
            "end": "2026-09-30",
            "lot_size": 500,
            "orig_getter": get_nestle_200_sma_strategy,
            "enh_getter": get_nestle_200_sma_enhanced_strategy,
        },
        {
            "symbol": "HINDUNILVR",
            "cache": "data/cache/HINDUNILVR_NSE_15m_2024-01-01_2025-09-30.parquet",
            "start": "2024-01-01",
            "end": "2025-09-30",
            "lot_size": 300,
            "orig_getter": get_hindunilvr_200_sma_strategy,
            "enh_getter": get_hindunilvr_200_sma_enhanced_strategy,
        },
        {
            "symbol": "ALKEM",
            "cache": "data/cache/ALKEM_NSE_15m_2024-01-01_2025-09-30.parquet",
            "start": "2024-01-01",
            "end": "2025-09-30",
            "lot_size": 125,
            "orig_getter": get_alkem_200_sma_strategy,
            "enh_getter": get_alkem_200_sma_enhanced_strategy,
        },
    ]

    records = []

    for item in stocks:
        sym = item["symbol"]
        print(f"\n⚡ Evaluating {sym} ({item['start']} to {item['end']})...")
        df = pd.read_parquet(PROJECT_ROOT / item["cache"])
        df = cal.add_dte_column(df)

        # Run Original
        bt_orig = Backtester(strategy=item["orig_getter"](), cost_model=cost_model, lot_size=item["lot_size"])
        r_orig = bt_orig.run(df, start_date=item["start"], end_date=item["end"])
        m_o = r_orig.metrics

        # Run Enhanced
        bt_enh = Backtester(strategy=item["enh_getter"](), cost_model=cost_model, lot_size=item["lot_size"])
        r_enh = bt_enh.run(df, start_date=item["start"], end_date=item["end"])
        m_e = r_enh.metrics

        pnl_diff = m_e.get("total_pnl", 0) - m_o.get("total_pnl", 0)

        records.append({
            "Stock": sym,
            "Period": f"{item['start'][:4]}–{item['end'][:4]}",
            "Orig Trades": len(r_orig.trades),
            "Enh Trades": len(r_enh.trades),
            "Orig WinRate": f"{m_o.get('win_rate_pct', 0):.1f}%",
            "Enh WinRate": f"{m_e.get('win_rate_pct', 0):.1f}%",
            "Orig Friction": f"₹{r_orig.total_costs:,.0f}",
            "Enh Friction": f"₹{r_enh.total_costs:,.0f}",
            "Orig Net PnL": f"₹{m_o.get('total_pnl', 0):+,.0f}",
            "Enh Net PnL": f"₹{m_e.get('total_pnl', 0):+,.0f}",
            "Total Alpha Gain": f"₹{pnl_diff:+,.0f}",
        })

    summary_df = pd.DataFrame(records)
    print("\n" + "=" * 105)
    print(" 📊 HEAD-TO-HEAD PERFORMANCE SCORECARD")
    print("=" * 105)
    print(summary_df.to_string(index=False))
    print("=" * 105)


if __name__ == "__main__":
    main()
