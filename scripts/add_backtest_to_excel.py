"""
Export Yearly Backtest Metrics and Full Trade Log to Excel:
Adds 'Yearly_Performance_Metrics' and 'All_Trades_Log' tabs to
data/exports/NESTLEIND_15m_2022_2026.xlsx.
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar


def main():
    print("=" * 90)
    print(" 📊 Embedding Yearly Performance Metrics & Full Trade Log into Excel Workbook")
    print("=" * 90)

    cache_path = PROJECT_ROOT / "data" / "cache" / "NESTLEIND_NSE_15m_2022-01-03_2026-09-30.parquet"
    excel_path = PROJECT_ROOT / "data" / "exports" / "NESTLEIND_15m_2022_2026.xlsx"

    if not cache_path.exists():
        print(f"❌ Cache file not found: {cache_path}")
        return

    print("⚡ Loading Parquet cache...", end=" ", flush=True)
    df = pd.read_parquet(cache_path)
    print(f"✅ Loaded {len(df):,} candles.")

    # Add DTE column
    cal = ExpiryCalendar()
    df = cal.add_dte_column(df)

    # Initialize Backtester with 1 Lot = 500 Shares
    strategy = get_nestle_200_sma_strategy()
    cost_model = TransactionCostModel(brokerage_per_order=0.0, futures_slippage_pct=0.0005)
    backtester = Backtester(strategy=strategy, cost_model=cost_model, lot_size=500)

    # 1. Compute Year-by-Year Performance Metrics
    print("\n⚙️ Calculating individual year performance metrics...")
    yearly_metrics_records = []
    years = [2022, 2023, 2024, 2025, 2026]

    for yr in years:
        s_date = f"{yr}-01-01"
        e_date = f"{yr}-12-31" if yr < 2026 else "2026-09-30"
        print(f"   • Running Backtest for Year {yr} ({s_date} to {e_date})...", end=" ", flush=True)

        res = backtester.run(df, start_date=s_date, end_date=e_date)
        m = res.metrics

        yearly_metrics_records.append({
            "Period / Year": str(yr),
            "Initial Capital (₹)": 500000.0,
            "Final Equity (₹)": round(m.get("final_equity", 0.0), 2),
            "Total Net PnL (₹)": round(m.get("total_pnl", 0.0), 2),
            "Return (%)": round(m.get("total_return_pct", 0.0), 2),
            "Max Drawdown (%)": round(m.get("max_drawdown_pct", 0.0), 2),
            "Max Drawdown (Days)": int(m.get("max_drawdown_duration_days", 0)),
            "Completed Trades": int(m.get("total_trades", 0)),
            "Winning Trades": int(m.get("winning_trades", 0)),
            "Losing Trades": int(m.get("losing_trades", 0)),
            "Win Rate (%)": round(m.get("win_rate_pct", 0.0), 2),
            "Profit Factor": round(m.get("profit_factor", 0.0), 2),
            "Total Friction Paid (₹)": round(res.total_costs, 2),
        })
        print(f"✅ Net PnL: ₹{m.get('total_pnl', 0.0):+,.2f} | Friction: ₹{res.total_costs:,.2f}")

    # Full 5-Year Cumulative Backtest
    print("\n   • Running Full 5-Year Backtest (2022-01-03 to 2026-09-30)...", end=" ", flush=True)
    full_res = backtester.run(df, start_date="2022-01-03", end_date="2026-09-30")
    full_m = full_res.metrics

    yearly_metrics_records.append({
        "Period / Year": "FULL_PERIOD (2022–2026)",
        "Initial Capital (₹)": 500000.0,
        "Final Equity (₹)": round(full_m.get("final_equity", 0.0), 2),
        "Total Net PnL (₹)": round(full_m.get("total_pnl", 0.0), 2),
        "Return (%)": round(full_m.get("total_return_pct", 0.0), 2),
        "Max Drawdown (%)": round(full_m.get("max_drawdown_pct", 0.0), 2),
        "Max Drawdown (Days)": int(full_m.get("max_drawdown_duration_days", 0)),
        "Completed Trades": int(full_m.get("total_trades", 0)),
        "Winning Trades": int(full_m.get("winning_trades", 0)),
        "Losing Trades": int(full_m.get("losing_trades", 0)),
        "Win Rate (%)": round(full_m.get("win_rate_pct", 0.0), 2),
        "Profit Factor": round(full_m.get("profit_factor", 0.0), 2),
        "Total Friction Paid (₹)": round(full_res.total_costs, 2),
    })
    print("✅ Completed!")

    perf_df = pd.DataFrame(yearly_metrics_records)

    # 2. Compile Complete Trade Log (All 493 Trades)
    print("\n📋 Compiling Complete Trade Log for all trades...")
    trade_rows = []
    cum_pnl = 0.0
    equity = 500000.0

    for idx, t in enumerate(full_res.trades, 1):
        net = t.pnl_net if t.pnl_net is not None else 0.0
        cum_pnl += net
        equity += net
        contract_val = t.entry_price * 500 if t.entry_price else 0.0

        trade_rows.append({
            "Trade #": idx,
            "Year": t.entry_time.year if t.entry_time else None,
            "Set ID": t.set_id,
            "Action": t.action.value,
            "Entry Time (IST)": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "",
            "Entry Price (₹)": round(t.entry_price, 2) if t.entry_price else None,
            "Exit Time (IST)": t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "",
            "Exit Price (₹)": round(t.exit_price, 2) if t.exit_price else None,
            "Contract Value (₹)": round(contract_val, 2),
            "Gross PnL (₹)": round(t.pnl_gross, 2) if t.pnl_gross is not None else 0.0,
            "Friction Costs (₹)": round(t.costs.total, 2) if t.costs else 0.0,
            "Net PnL (₹)": round(net, 2),
            "Cumulative PnL (₹)": round(cum_pnl, 2),
            "Account Equity (₹)": round(equity, 2),
            "Exit Reason": t.exit_reason or "OPEN",
        })

    trades_df = pd.DataFrame(trade_rows)
    print(f"✅ Formatted {len(trades_df):,} trades.")

    # 3. Read Existing Sheets from Excel
    print("\n📖 Reading existing Excel workbook sheets...")
    xl = pd.ExcelFile(excel_path)
    candles_df = xl.parse("15m_Candles")
    audit_df = xl.parse("Holiday_Audit_Report")
    market_summary_df = xl.parse("Yearly_Summary")

    # 4. Write Enhanced Multi-Tab Excel Workbook
    print(f"\n💾 Writing updated Excel file to {excel_path.name}...")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        perf_df.to_excel(writer, sheet_name="Yearly_Performance", index=False)
        trades_df.to_excel(writer, sheet_name="All_Trades_Log", index=False)
        candles_df.to_excel(writer, sheet_name="15m_Candles", index=False)
        audit_df.to_excel(writer, sheet_name="Holiday_Audit_Report", index=False)
        market_summary_df.to_excel(writer, sheet_name="Market_Data_Summary", index=False)

    file_size_mb = excel_path.stat().st_size / (1024 * 1024)
    print(f"✅ Enhanced Excel Workbook written successfully! File size: {file_size_mb:.2f} MB")
    print("\nIncluded Tabs:")
    print("  1. 'Yearly_Performance'    : Initial Capital, Final Equity, Net PnL, Return %, MaxDD %, Friction Paid per year")
    print("  2. 'All_Trades_Log'        : All 493 trades with entry/exit times, prices, costs, net PnL, and equity curve")
    print("  3. '15m_Candles'           : Raw 29,290 15m OHLCV candles")
    print("  4. 'Holiday_Audit_Report'  : Complete daily holiday and trading session audit")
    print("  5. 'Market_Data_Summary'   : Yearly OHLC prices and volumes")
    print("=" * 90)


if __name__ == "__main__":
    main()
