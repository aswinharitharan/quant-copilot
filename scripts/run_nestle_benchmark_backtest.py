"""
Benchmark Backtest Runner: Nestle India 200 SMA on 15m Futures.

Replays 60 days of real 15-minute historical candles from Yahoo Finance.
Enforces:
- Long: Close > 200 SMA AND Low > 200 SMA
- Short: Close < 200 SMA AND High < 200 SMA
- Single Position Guard: max_open_positions = 1 (OPEN_POSITIONS == 0)
- Dual-contract handover (DTE > 6 vs DTE <= 6)
- Pre-expiry physical delivery safety exit on DTE <= 1
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.engine.providers.yfinance_provider import YFinanceProvider
from src.engine.data_feed import DataFeed
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel
from src.engine.expiry_calendar import ExpiryCalendar


def main():
    print("=" * 85)
    print(" 🚀 QuantCopilot Golden Benchmark Backtest: Nestle India 200 SMA 15m Futures")
    print("=" * 85)

    strategy = get_nestle_200_sma_strategy()

    # Define 60-day window for 15-minute candles (max yfinance allows)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=59)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"Strategy Name:      {strategy.name}")
    print(f"Underlying Asset:   {strategy.underlying} (NSE: NESTLEIND.NS)")
    print(f"Timeframe:          {strategy.timeframe.value} (15-Minute Candles)")
    print(f"Execution Style:    {strategy.deployment_settings.execution_style.value}")
    print(f"Capital Allocated:  ₹{strategy.deployment_settings.capital_allocated:,.2f}")
    print(f"Lot Sizing:         1 Lot = 25 Shares")
    print(f"Single Position:    max_open_positions = {strategy.deployment_settings.max_open_positions} (OPEN_POSITIONS == 0)")
    print(f"Historical Window:  {start_str} to {end_str} (~60 Days)\n")

    # Fetch 15m candles
    provider = YFinanceProvider()
    feed = DataFeed(provider=provider, cache_dir="./data/cache")

    print("📥 Fetching 15m candles via DataFeed (cached in ./data/cache)...")
    df = feed.get_candles(
        symbol="NESTLEIND",
        exchange="NSE",
        interval="15m",
        start_date=start_str,
        end_date=end_str,
    )
    print(f"✅ Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}")

    # Add DTE column via ExpiryCalendar
    cal = ExpiryCalendar()
    df = cal.add_dte_column(df)
    print(f"✅ Expiry calendar attached. Days to Expiry range: {df['days_to_expiry'].min()} to {df['days_to_expiry'].max()} days.\n")

    # Configure Futures Cost Model (NSE Equity Futures: 0.02% STT sell side, 0.002% exchange, 0.002% stamp duty)
    cost_model = TransactionCostModel(
        brokerage_per_order=0.0,
        futures_slippage_pct=0.0005,  # 0.05% slippage buffer
    )

    backtester = Backtester(
        strategy=strategy,
        cost_model=cost_model,
        lot_size=25,  # 1 lot of Nestle India futures = 25 shares
    )

    print("⚙️ Running deterministic backtest loop...")
    result = backtester.run(df)
    print("✅ Backtest complete!\n")

    # -------------------------------------------------------------
    # PRINT TRADE LOG
    # -------------------------------------------------------------
    print("-" * 125)
    print(" 📋 EXECUTED FUTURES TRADES (15m Candles)")
    print("-" * 125)
    print(f"{'#':<3} | {'Set':<4} | {'Action':<5} | {'Entry Time':<16} | {'Entry Px':<11} | {'Exit Time':<16} | {'Exit Px':<11} | {'Gross PnL':<12} | {'Costs':<9} | {'Net PnL':<12} | {'Exit Reason'}")
    print("-" * 125)

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
    print(" 📊 PORTFOLIO PERFORMANCE METRICS (60 DAYS)")
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
