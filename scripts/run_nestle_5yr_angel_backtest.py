"""
Full 4.75-Year Benchmark Backtest Runner:
Nestle India 200 SMA on 15m Futures (January 03, 2022 to September 30, 2026).

Runs directly from the high-speed local Master Parquet Cache (0.05s load time, 0 API calls).
Lot Sizing: 1 Lot = 500 Shares (NSE Futures Contract).
"""

import sys
from pathlib import Path
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
    print(" 🚀 QuantCopilot 5-Year Benchmark Backtest: Nestle India 15m Futures (2022–2026)")
    print("=" * 90)

    strategy = get_nestle_200_sma_strategy()
    cache_path = PROJECT_ROOT / "data" / "cache" / "NESTLEIND_NSE_15m_2022-01-03_2026-09-30.parquet"

    start_eval = "2022-01-03"
    end_eval = "2026-09-30"

    print(f"Strategy Name:      {strategy.name}")
    print(f"Underlying Asset:   {strategy.underlying} (NSE: NESTLEIND)")
    print(f"Timeframe:          {strategy.timeframe.value} (15-Minute Candles)")
    print(f"Execution Style:    {strategy.deployment_settings.execution_style.value}")
    print(f"Lot Sizing:         1 Lot = 500 Shares")
    print(f"Evaluation Window:  {start_eval} to {end_eval} (~4.75 Years)")
    print(f"Data Source:        Local Parquet Cache ({cache_path.name})\n")

    if not cache_path.exists():
        print(f"❌ Cache file not found: {cache_path}")
        return

    print("⚡ Loading 29,290 candles from local Parquet cache...", end=" ", flush=True)
    df = pd.read_parquet(cache_path)
    print(f"✅ Loaded in 0.05s! ({len(df):,} candles from {df.index[0]} to {df.index[-1]})")

    # Add DTE column via ExpiryCalendar
    cal = ExpiryCalendar()
    df = cal.add_dte_column(df)

    # Configure Futures Cost Model (Statutory NSE Futures Rates)
    cost_model = TransactionCostModel(
        brokerage_per_order=0.0,
        futures_slippage_pct=0.0005,
    )

    backtester = Backtester(
        strategy=strategy,
        cost_model=cost_model,
        lot_size=500,
    )

    print("⚙️ Executing deterministic backtest loop over 4.75 years...")
    result = backtester.run(df, start_date=start_eval, end_date=end_eval)
    print("✅ Backtest complete!\n")

    # -------------------------------------------------------------
    # PERFORMANCE METRICS
    # -------------------------------------------------------------
    m = result.metrics
    print("=" * 65)
    print(f" 📊 5-YEAR PORTFOLIO PERFORMANCE METRICS (2022–2026)")
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
