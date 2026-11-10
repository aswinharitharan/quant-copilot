"""
End-to-End Pipeline & Backtest Exporter:
Alkem Laboratories (NSE: ALKEM) 200 SMA on 15m Futures (Jan 2024 to Sep 2025).

Features:
1. Paced 90-day chunked retrieval with Angel One SmartAPI and checkpoint caching.
2. Automatic holiday cross-validation against config/nse_holidays.csv.
3. High-speed local Parquet caching (exact + canonical master).
4. Deterministic Backtest execution (1 Lot = 125 Shares, 4-Set Dual-Contract Handover).
5. Comprehensive Multi-Tab Excel Export matching NESTLEIND_15m_2022_2026.xlsx:
   - 'Yearly_Performance'
   - 'All_Trades_Log'
   - '15m_Candles'
   - 'Holiday_Audit_Report'
   - 'Market_Data_Summary'
"""

import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.providers.angel_provider import AngelOneProvider
from src.engine.data_feed import DataProviderError
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar
from src.strategies.alkem_200_sma import get_alkem_200_sma_strategy


def generate_90day_chunks(start_date_str: str, end_date_str: str) -> List[Tuple[str, str]]:
    """Slice date range into safe 90-calendar-day intervals."""
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    chunks = []
    current_start = start_dt

    while current_start <= end_dt:
        current_end = min(current_start + timedelta(days=90), end_dt)
        chunks.append((current_start.strftime("%Y-%m-%d"), current_end.strftime("%Y-%m-%d")))
        current_start = current_end + timedelta(days=1)

    return chunks


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
    print(" 🚀 QuantCopilot Benchmark Backtest: Alkem Laboratories 15m Futures (2024–2025)")
    print("=" * 90)

    symbol = "ALKEM"
    exchange = "NSE"
    interval = "15m"
    # Fetch starting Dec 2023 for 200 SMA indicator warmup
    fetch_start = "2023-12-01"
    fetch_end = "2025-09-30"

    backtest_start = "2024-01-01"
    backtest_end = "2025-09-30"

    lot_size = 125  # NSE Futures lot size for ALKEM

    cache_dir = PROJECT_ROOT / "data" / "cache"
    exports_dir = PROJECT_ROOT / "data" / "exports"
    cache_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    master_cache_path = cache_dir / f"{symbol}_{exchange}_{interval}.parquet"
    exact_cache_path = cache_dir / f"{symbol}_{exchange}_{interval}_{backtest_start}_{backtest_end}.parquet"
    excel_path = exports_dir / f"{symbol}_{interval}_2024_2025.xlsx"

    print(f"Underlying Asset:   {symbol} ({exchange})")
    print(f"Timeframe:          {interval} (15-Minute Candles)")
    print(f"Evaluation Window:  {backtest_start} to {backtest_end} (2 Years)")
    print(f"Lot Sizing:         1 Lot = {lot_size} Shares")
    print(f"Warmup Window:      {fetch_start} to {fetch_end}")
    print(f"Target Excel File:  {excel_path.relative_to(PROJECT_ROOT)}\n")

    # -------------------------------------------------------------------------
    # 1. FETCH / LOAD HISTORICAL CANDLES
    # -------------------------------------------------------------------------
    full_df = None
    if master_cache_path.exists():
        print(f"⚡ Found existing master cache: {master_cache_path.name}")
        df_existing = pd.read_parquet(master_cache_path)
        if not df_existing.empty and df_existing.index.min() <= pd.Timestamp(fetch_start, tz="Asia/Kolkata") and df_existing.index.max() >= pd.Timestamp("2025-09-30 15:00:00", tz="Asia/Kolkata"):
            print(f"✅ Master cache fully covers required span ({len(df_existing):,} candles).")
            full_df = df_existing

    if full_df is None:
        print("🔌 Connecting to Angel One SmartAPI historical market data feed...")
        try:
            provider = AngelOneProvider()
            print("✅ Logged in successfully!")
        except DataProviderError as e:
            print(f"❌ Login failed: {e}")
            return

        chunks = generate_90day_chunks(fetch_start, fetch_end)
        print(f"📅 Sliced into {len(chunks)} retrieval windows.")

        temp_dir = cache_dir / f"temp_chunks_{symbol}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        collected_dfs = []
        for i, (c_start, c_end) in enumerate(chunks, 1):
            chunk_file = temp_dir / f"chunk_{i:02d}_{c_start}_{c_end}.parquet"
            if chunk_file.exists():
                print(f"   [{i:02d}/{len(chunks)}] Loaded from checkpoint: {c_start} to {c_end}")
                df_c = pd.read_parquet(chunk_file)
                collected_dfs.append(df_c)
            else:
                print(f"   [{i:02d}/{len(chunks)}] Fetching from API: {c_start} to {c_end}...", end=" ", flush=True)
                df_c = provider.fetch_candles(
                    symbol=symbol,
                    exchange=exchange,
                    interval=interval,
                    start_date=c_start,
                    end_date=c_end,
                )
                df_c.to_parquet(chunk_file, engine="pyarrow")
                collected_dfs.append(df_c)
                print(f"✅ {len(df_c):,} candles")
                time.sleep(1.5)  # Safe delay between chunks

        full_df = pd.concat(collected_dfs)
        full_df = full_df[~full_df.index.duplicated(keep="last")].sort_index()

        # Save caches
        full_df.to_parquet(master_cache_path, engine="pyarrow")
        full_df.to_parquet(exact_cache_path, engine="pyarrow")
        print(f"\n💾 Saved master parquet cache: {master_cache_path.name} ({len(full_df):,} candles)")

    # -------------------------------------------------------------------------
    # 2. RUN DETERMINISTIC BACKTEST
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print(" ⚙️ Executing Deterministic 200 SMA Backtest on ALKEM Futures")
    print("=" * 90)

    # Add DTE column
    cal = ExpiryCalendar()
    df_with_dte = cal.add_dte_column(full_df)

    strategy = get_alkem_200_sma_strategy()
    cost_model = TransactionCostModel(brokerage_per_order=0.0, futures_slippage_pct=0.0005)
    backtester = Backtester(strategy=strategy, cost_model=cost_model, lot_size=lot_size)

    # Compute Year-by-Year Performance
    years = [2024, 2025]
    yearly_metrics_records = []

    for yr in years:
        s_date = f"{yr}-01-01"
        e_date = f"{yr}-12-31" if yr < 2025 else "2025-09-30"
        print(f"   • Running Year {yr} ({s_date} to {e_date})...", end=" ", flush=True)
        res_yr = backtester.run(df_with_dte, start_date=s_date, end_date=e_date)
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
        print(f"✅ Net PnL: ₹{m.get('total_pnl', 0.0):+,.2f} | Trades: {m.get('total_trades', 0)}")

    # Full Cumulative 2-Year Backtest
    print(f"\n   • Running Cumulative 2-Year Backtest ({backtest_start} to {backtest_end})...", end=" ", flush=True)
    full_res = backtester.run(df_with_dte, start_date=backtest_start, end_date=backtest_end)
    full_m = full_res.metrics

    yearly_metrics_records.append({
        "Period / Year": f"FULL_PERIOD (2024–2025)",
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
    # 3. BUILD ALL TRADES LOG SHEET
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
    # 4. CANDLES & HOLIDAY AUDIT REPORT
    # -------------------------------------------------------------------------
    eval_candles = full_df.loc[
        (full_df.index >= pd.Timestamp(backtest_start, tz="Asia/Kolkata")) &
        (full_df.index <= pd.Timestamp(f"{backtest_end} 23:59:59", tz="Asia/Kolkata"))
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
    # 5. MARKET DATA SUMMARY SHEET
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
    # 6. WRITE 5-TAB EXCEL WORKBOOK
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
    # 7. PERFORMANCE SUMMARY DISPLAY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 90)
    print(" 📊 ALKEM LABORATORIES (ALKEM) 200 SMA PERFORMANCE SUMMARY (2024–2025)")
    print("=" * 90)
    print(perf_df.to_string(index=False))
    print("=" * 90)
    print(f"Total Completed Trades: {len(trades_df):,}")
    print(f"Excel Export Location:  {excel_path.resolve()}")
    print("=" * 90)


if __name__ == "__main__":
    main()

