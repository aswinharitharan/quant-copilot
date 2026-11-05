"""
Benchmark Backtest Runner using DhanHQ Data Provider:
Nestle India 200 SMA on 15m Futures (July 26 – August 26).

Connects to DhanHQ via DhanHQProvider, fetches 15m candles with warmup,
caches candles to Parquet, and executes the deterministic backtest loop.
"""

import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.engine.providers.dhan_provider import DhanHQProvider
from src.engine.data_feed import DataFeed, DataProviderError
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar


def main():
    print("=" * 85)
    print(" 🚀 QuantCopilot Benchmark Backtest via DhanHQ Provider: Nestle India 15m Futures")
    print("=" * 85)

    strategy = get_nestle_200_sma_strategy()

    # User test window: July 26 to August 26
    # Indicator warmup window: July 01 to July 25 (ensures 200 bars for 200 SMA on July 26)
    start_eval = "2026-07-26"
    end_eval = "2026-08-26"
    warmup_start = "2026-07-01"

    print(f"Strategy Name:      {strategy.name}")
    print(f"Underlying Asset:   {strategy.underlying} (NSE: NESTLEIND Equity / Futures)")
    print(f"Timeframe:          {strategy.timeframe.value} (15-Minute Candles)")
    print(f"Execution Style:    {strategy.deployment_settings.execution_style.value}")
    print(f"Lot Sizing:         1 Lot = 25 Shares")
    print(f"Evaluation Window:  {start_eval} to {end_eval} (~1 Month)")
    print(f"Indicator Warmup:   {warmup_start} to {start_eval} (~200 bars of 15m)\n")

    print("🔌 Initializing DhanHQProvider from environment credentials (.env)...")
    try:
        provider = DhanHQProvider()
        feed = DataFeed(provider=provider, cache_dir="./data/cache")
    except DataProviderError as e:
        print(f"❌ Configuration Error: {e}")
        return

    print(f"📥 Querying 15m candles for NESTLEIND from {warmup_start} to {end_eval}...")
    try:
        df = feed.get_candles(
            symbol="NESTLEIND",
            exchange="NSE",
            interval="15m",
            start_date=warmup_start,
            end_date=end_eval,
        )
    except DataProviderError as e:
        print("\n" + "!" * 85)
        print(f"⚠️  DhanHQ Data Fetch Failed:\n   {e}")
        print("!" * 85)
        if "DH-902" in str(e) or "Data APIs Plan" in str(e):
            print("\n📌 DIAGNOSIS:")
            print("   Your Dhan account has the FREE 'Trading API' plan enabled.")
            print("   Dhan charges for historical/intraday chart access under their 'Data APIs Plan'.")
            print("   To enable it on Dhan:")
            print("     1. Log in to web.dhan.co")
            print("     2. Go to My Profile -> Access DhanHQ APIs")
            print("     3. Check/Activate the 'Data API Plan' (or generate a fresh token with data access)")
        return

    print(f"✅ Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}")

    # Add DTE column via ExpiryCalendar
    cal = ExpiryCalendar()
    df = cal.add_dte_column(df)

    # Configure Futures Cost Model
    cost_model = TransactionCostModel(
        brokerage_per_order=0.0,
        futures_slippage_pct=0.0005,
    )

    backtester = Backtester(
        strategy=strategy,
        cost_model=cost_model,
        lot_size=25,
    )

    print("⚙️ Running deterministic backtest loop...")
    result = backtester.run(df, start_date=start_eval, end_date=end_eval)
    print("✅ Backtest complete!\n")

    # -------------------------------------------------------------
    # PRINT TRADE LOG
    # -------------------------------------------------------------
    print("-" * 125)
    print(f" 📋 EXECUTED FUTURES TRADES ({start_eval} to {end_eval})")
    print("-" * 125)
    print(f"{'#':<3} | {'Set':<4} | {'Action':<5} | {'Entry Time':<16} | {'Entry Px':<11} | {'Exit Time':<16} | {'Exit Px':<11} | {'Gross PnL':<12} | {'Costs':<9} | {'Net PnL':<12} | {'Exit Reason'}")
    print("-" * 125)

    if not result.trades:
        print("  No trades triggered in this test window.")
    else:
        for i, t in enumerate(result.trades, 1):
            entry_t = t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-"
            exit_t = t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-"
            gross = f"₹{t.pnl_gross:+,.2f}" if t.pnl_gross is not None else "-"
            costs = f"₹{t.costs.total:,.2f}" if t.costs else "₹0.00"
            net = f"₹{t.pnl_net:+,.2f}" if t.pnl_net is not None else "-"
            exit_p = f"₹{t.exit_price:,.2f}" if t.exit_price else "-"

            print(f"{i:<3} | {t.set_id:<4} | {t.action.value:<5} | {entry_t:<16} | {f'₹{t.entry_price:,.2f}':<11} | {exit_t:<16} | {exit_p:<11} | {gross:<12} | {costs:<9} | {net:<12} | {t.exit_reason or 'OPEN'}")

    print("-" * 125)

    # -------------------------------------------------------------
    # PERFORMANCE METRICS
    # -------------------------------------------------------------
    m = result.metrics
    print("\n" + "=" * 65)
    print(f" 📊 PORTFOLIO PERFORMANCE METRICS ({start_eval} to {end_eval})")
    print("=" * 65)
    metrics_summary = [
        ("Initial Margin Capital", f"₹{m.get('initial_capital', 0):,.2f}"),
        ("Final Equity", f"₹{m.get('final_equity', 0):,.2f}"),
        ("Total Net PnL", f"₹{m.get('total_pnl', 0):+,.2f}"),
        ("Total Return %", f"{m.get('total_return_pct', 0):+.2f}%"),
        ("Annualized Volatility", f"{m.get('annualized_volatility_pct', 0):.2f}%"),
        ("Sharpe Ratio (Rf=6.5%)", f"{m.get('sharpe_ratio', 0):.2f}"),
        ("Maximum Drawdown %", f"{m.get('max_drawdown_pct', 0):.2f}%"),
        ("Max Drawdown Duration", f"{m.get('max_drawdown_duration_days', 0)} days"),
        ("Total Completed Trades", f"{m.get('total_trades', 0)}"),
        ("Winning Trades", f"{m.get('winning_trades', 0)}"),
        ("Losing Trades", f"{m.get('losing_trades', 0)}"),
        ("Win Rate %", f"{m.get('win_rate_pct', 0):.2f}%"),
        ("Profit Factor", f"{m.get('profit_factor', 0):.2f}"),
        ("Total Friction Paid", f"₹{result.total_costs:,.2f}"),
    ]
    for label, val in metrics_summary:
        print(f"  {label:<30} : {val}")
    print("=" * 65)


if __name__ == "__main__":
    main()
