"""
Nestle India 200 SMA Futures Benchmark Backtest (Jan 2024 to Sep 2026)
with Updated Real-World Statutory Transaction Cost Model:

1. Slippage: Fixed ₹20 for BUY and ₹20 for SELL (₹40 round trip per trade).
2. STT: 0.05% charged on Sell value.
3. Exchange Turnover Charges: 0.00183% on total turnover.
4. State Stamp Duty: 0.002% on Buy side.
5. GST: 18% on (Slippage + SEBI Charges + Exchange Turnover Charges + Brokerage).
6. SEBI Charges: ₹10 per crore (0.0001%).

Generates comprehensive 5-tab Excel workbook:
data/exports/NESTLEIND_15m_2024_2026.xlsx
- 'Yearly_Performance'
- 'All_Trades_Log'
- '15m_Candles'
- 'Holiday_Audit_Report'
- 'Market_Data_Summary'
"""

import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar


def load_nse_holidays(holidays_csv_path: Path) -> Dict[date, str]:
    """Load official NSE holidays map."""
    if not holidays_csv_path.exists():
        return {}

    df = pd.read_csv(holidays_csv_path)
    holidays = {}
    for _, row in df.iterrows():
        try:
            d = pd.to_datetime(row["date"]).date()
            holidays[d] = str(row.get("name", "NSE Holiday"))
        except Exception:
            continue
    return holidays


def main():
    print("=" * 90)
    print(" 🚀 QuantCopilot Benchmark Backtest: Nestle India 15m Futures (2024–2026)")
    print(" ⚡ Updated Cost Model: ₹40 Fixed Slippage, 0.05% STT, 0.00183% Exch, 18% GST")
    print("=" * 90)

    symbol = "NESTLEIND"
    exchange = "NSE"
    interval = "15m"
    lot_size = 500  # 1 Lot = 500 Shares

    backtest_start = "2024-01-01"
    backtest_end = "2026-09-30"

    cache_path = PROJECT_ROOT / "data" / "cache" / "NESTLEIND_NSE_15m.parquet"
    if not cache_path.exists():
        cache_path = PROJECT_ROOT / "data" / "cache" / "NESTLEIND_NSE_15m_2022-01-03_2026-09-30.parquet"

    exports_dir = PROJECT_ROOT / "data" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    excel_path = exports_dir / f"{symbol}_{interval}_2024_2026.xlsx"

    print(f"Underlying Asset:   {symbol} ({exchange})")
    print(f"Timeframe:          {interval} (15-Minute Candles)")
    print(f"Evaluation Window:  {backtest_start} to {backtest_end} (~2.75 Years)")
    print(f"Lot Sizing:         1 Lot = {lot_size} Shares")
    print(f"Data Source:        {cache_path.name}")
    print(f"Target Excel File:  {excel_path.relative_to(PROJECT_ROOT)}\n")

    if not cache_path.exists():
        print(f"❌ Cache file not found: {cache_path}")
        return

    print("⚡ Loading Parquet cache...", end=" ", flush=True)
    df_raw = pd.read_parquet(cache_path)
    print(f"✅ Loaded {len(df_raw):,} candles.")

    # Add DTE column
    cal = ExpiryCalendar()
    df = cal.add_dte_column(df_raw)

    # Instantiate updated TransactionCostModel with user's rules:
    # 1. Slippage = ₹20 buy, ₹20 sell (fixed)
    # 2. STT = 0.05% on sell
    # 3. Exchange = 0.00183% on turnover
    # 4. Stamp duty = 0.002% on buy
    # 5. GST = 18% on (Slippage + SEBI + Exchange)
    # 6. SEBI = ₹10/crore
    cost_model = TransactionCostModel(
        brokerage_per_order=0.0,
        futures_slippage_fixed=20.0,
        futures_stt_pct=0.0005,
        futures_exchange_pct=0.0000183,
    )

    strategy = get_nestle_200_sma_strategy()
    backtester = Backtester(strategy=strategy, cost_model=cost_model, lot_size=lot_size)

    # -------------------------------------------------------------------------
    # 1. YEAR-BY-YEAR PERFORMANCE
    # -------------------------------------------------------------------------
    print("\n⚙️ Calculating individual year performance metrics with updated costs...")
    years = [2024, 2025, 2026]
    yearly_metrics_records = []

    for yr in years:
        s_date = f"{yr}-01-01"
        e_date = f"{yr}-12-31" if yr < 2026 else backtest_end
        print(f"   • Running Year {yr} ({s_date} to {e_date})...", end=" ", flush=True)

        res_yr = backtester.run(df, start_date=s_date, end_date=e_date)
        m = res_yr.metrics

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
            "Total Friction Paid (₹)": round(res_yr.total_costs, 2),
        })
        print(f"✅ Net PnL: ₹{m.get('total_pnl', 0.0):+,.2f} | Friction: ₹{res_yr.total_costs:,.2f}")

    # Full Cumulative Backtest (2024-01-01 to 2026-09-30)
    print(f"\n   • Running Cumulative Period ({backtest_start} to {backtest_end})...", end=" ", flush=True)
    full_res = backtester.run(df, start_date=backtest_start, end_date=backtest_end)
    full_m = full_res.metrics

    yearly_metrics_records.append({
        "Period / Year": f"FULL_PERIOD (2024–2026)",
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

    # -------------------------------------------------------------------------
    # 2. BUILD ALL TRADES LOG
    # -------------------------------------------------------------------------
    trade_rows = []
    cum_pnl = 0.0
    equity = 500000.0

    for idx, t in enumerate(full_res.trades, 1):
        net = t.pnl_net if t.pnl_net is not None else 0.0
        cum_pnl += net
        equity += net
        contract_val = (t.entry_price or 0.0) * lot_size

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

    # -------------------------------------------------------------------------
    # 3. CANDLES & HOLIDAY AUDIT REPORT
    # -------------------------------------------------------------------------
    eval_candles = df.loc[
        (df.index >= pd.Timestamp(backtest_start, tz="Asia/Kolkata")) &
        (df.index <= pd.Timestamp(f"{backtest_end} 23:59:59", tz="Asia/Kolkata"))
    ].copy()

    export_candles = eval_candles.copy()
    export_candles.index = export_candles.index.tz_convert("Asia/Kolkata")
    export_candles["Date"] = export_candles.index.strftime("%Y-%m-%d")
    export_candles["Time_IST"] = export_candles.index.strftime("%H:%M")
    export_candles = export_candles[["Date", "Time_IST", "open", "high", "low", "close", "volume"]]
    export_candles.columns = ["Date", "Time (IST)", "Open (₹)", "High (₹)", "Low (₹)", "Close (₹)", "Volume"]

    # Holiday audit report
    nse_holidays = load_nse_holidays(PROJECT_ROOT / "config" / "nse_holidays.csv")
    trading_dates = set(ts.date() for ts in eval_candles.index.normalize().unique())

    cur_date = datetime.strptime(backtest_start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(backtest_end, "%Y-%m-%d").date()

    audit_records = []
    while cur_date <= end_dt:
        weekday = cur_date.weekday()
        day_name = cur_date.strftime("%A")

        if cur_date in trading_dates:
            day_candles = eval_candles.loc[cur_date.strftime("%Y-%m-%d")]
            num_c = len(day_candles)
            status = "TRADING_DAY"
            note = f"{num_c} candles (Normal Session)" if num_c == 25 else f"{num_c} candles (Special Session/Muhurat)"
            audit_records.append({
                "Date": cur_date.strftime("%Y-%m-%d"),
                "Day": day_name,
                "Status": status,
                "Candles": num_c,
                "Details": note,
            })
        else:
            if weekday in [5, 6]:
                audit_records.append({
                    "Date": cur_date.strftime("%Y-%m-%d"),
                    "Day": day_name,
                    "Status": "WEEKEND",
                    "Candles": 0,
                    "Details": "Market Closed (Saturday/Sunday)",
                })
            elif cur_date in nse_holidays:
                h_name = nse_holidays[cur_date]
                audit_records.append({
                    "Date": cur_date.strftime("%Y-%m-%d"),
                    "Day": day_name,
                    "Status": "NSE_HOLIDAY",
                    "Candles": 0,
                    "Details": f"Market Closed ({h_name})",
                })
            else:
                audit_records.append({
                    "Date": cur_date.strftime("%Y-%m-%d"),
                    "Day": day_name,
                    "Status": "UNEXPECTED_MISSING",
                    "Candles": 0,
                    "Details": "⚠️ No candles returned for this weekday!",
                })

        cur_date += timedelta(days=1)

    audit_df = pd.DataFrame(audit_records)

    # -------------------------------------------------------------------------
    # 4. MARKET DATA SUMMARY SHEET
    # -------------------------------------------------------------------------
    yearly_rows = []
    for yr, group in eval_candles.groupby(eval_candles.index.year):
        unique_days = len(group.index.normalize().unique())
        yearly_rows.append({
            "Year": yr,
            "Trading Days": unique_days,
            "15m Candles": len(group),
            "Year Open (₹)": round(group["open"].iloc[0], 2),
            "Year High (₹)": round(group["high"].max(), 2),
            "Year Low (₹)": round(group["low"].min(), 2),
            "Year Close (₹)": round(group["close"].iloc[-1], 2),
            "Total Volume": int(group["volume"].sum()),
        })
    market_summary_df = pd.DataFrame(yearly_rows)

    # -------------------------------------------------------------------------
    # 5. WRITE 5-TAB EXCEL WORKBOOK
    # -------------------------------------------------------------------------
    print(f"\n💾 Writing Multi-Tab Excel Workbook: {excel_path.name}...")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        perf_df.to_excel(writer, sheet_name="Yearly_Performance", index=False)
        trades_df.to_excel(writer, sheet_name="All_Trades_Log", index=False)
        export_candles.to_excel(writer, sheet_name="15m_Candles", index=False)
        audit_df.to_excel(writer, sheet_name="Holiday_Audit_Report", index=False)
        market_summary_df.to_excel(writer, sheet_name="Market_Data_Summary", index=False)

    file_size_mb = excel_path.stat().st_size / (1024 * 1024)
    print(f"✅ Enhanced Excel Workbook written successfully! File size: {file_size_mb:.2f} MB")

    # -------------------------------------------------------------------------
    # 6. PERFORMANCE SUMMARY DISPLAY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print(" 📊 NESTLE INDIA (NESTLEIND) 200 SMA PERFORMANCE SUMMARY (2024–2026)")
    print("=" * 90)
    print(perf_df.to_string(index=False))
    print("=" * 90)
    print(f"Total Completed Trades: {len(trades_df):,}")
    print(f"Excel Export Location:  {excel_path.resolve()}")
    print("=" * 90)


if __name__ == "__main__":
    main()

