"""
5-Year Backtest Verification Script: Reliance Industries Golden Cross (50 EMA / 200 EMA)

Fetches historical daily data via YFinanceProvider and runs our deterministic Backtester.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schema.strategy import (
    StrategyDefinition,
    StrategySet,
    Leg,
    ConditionGroup,
    ConditionNode,
    Operand,
    OperandType,
    ComparisonOperator,
    LogicalOperator,
    IndicatorDefinition,
    DeploymentSettings,
    InstrumentType,
    OrderAction,
    TimeFrame,
    ExecutionStyle,
)
from src.engine.providers.yfinance_provider import YFinanceProvider
from src.engine.data_feed import DataFeed
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel


def build_reliance_golden_cross_strategy() -> StrategyDefinition:
    """Build the official 50 EMA / 200 EMA Golden Cross Strategy schema."""
    entry_condition = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="EMA", params={"period": 50, "field": "close"}),
                ),
                operator=ComparisonOperator.CROSSES_ABOVE,
                right_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="EMA", params={"period": 200, "field": "close"}),
                ),
            )
        ],
    )

    exit_condition = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="EMA", params={"period": 50, "field": "close"}),
                ),
                operator=ComparisonOperator.CROSSES_BELOW,
                right_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="EMA", params={"period": 200, "field": "close"}),
                ),
            )
        ],
    )

    leg = Leg(
        leg_id="leg_reliance_eq",
        instrument_type=InstrumentType.EQUITY,
        action=OrderAction.BUY,
        lots=50,  # 50 shares
    )

    strat_set = StrategySet(
        set_id=1,
        name="Golden Cross Trend Follower",
        entry_conditions=entry_condition,
        legs=[leg],
        exit_conditions=exit_condition,
    )

    deployment = DeploymentSettings(
        capital_allocated=100000.0,
        max_daily_loss=10000.0,
        max_trades_per_day=2,
        execution_style=ExecutionStyle.POSITIONAL,
        market_open_delay_minutes=0,
    )

    return StrategyDefinition(
        id="reliance_golden_cross_5y",
        name="Reliance Industries 50/200 EMA Golden Cross",
        description="Buys on 50 EMA crossing above 200 EMA, exits on cross below",
        author="QuantCopilot",
        underlying="RELIANCE",
        timeframe=TimeFrame.D1,
        sets=[strat_set],
        deployment_settings=deployment,
    )


def main():
    print("=" * 75)
    print(" 🚀 QuantCopilot Deterministic Backtester — 5-Year Verification Run")
    print("=" * 75)

    strategy = build_reliance_golden_cross_strategy()

    # Define 5-year simulation window + 1.5 years warmup for 200 EMA
    end_date = datetime.now()
    sim_start_date = end_date - timedelta(days=5 * 365)
    data_fetch_start = sim_start_date - timedelta(days=500)  # 500 days warmup

    fetch_start_str = data_fetch_start.strftime("%Y-%m-%d")
    sim_start_str = sim_start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"Strategy:         {strategy.name}")
    print(f"Underlying:       {strategy.underlying} (NSE: RELIANCE.NS)")
    print(f"Timeframe:        {strategy.timeframe.value} (Daily)")
    print(f"Execution Style:  {strategy.deployment_settings.execution_style.value}")
    print(f"Initial Capital:  ₹{strategy.deployment_settings.capital_allocated:,.2f}")
    print(f"Position Size:    50 Shares")
    print(f"Warmup History:   {fetch_start_str} to {sim_start_str}")
    print(f"5-Year Test Window: {sim_start_str} to {end_str}\n")

    # Fetch via DataFeed (with automatic local Parquet caching)
    provider = YFinanceProvider()
    feed = DataFeed(provider=provider, cache_dir="./data/cache")

    print("📥 Fetching candles via DataFeed (cached in ./data/cache)...")
    df = feed.get_candles(
        symbol="RELIANCE",
        exchange="NSE",
        interval="1d",
        start_date=fetch_start_str,
        end_date=end_str,
    )
    print(f"✅ Loaded {len(df)} total daily candles from {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}\n")

    # Run deterministic backtest
    cost_model = TransactionCostModel(
        brokerage_per_order=0.0,    # Zero brokerage delivery
        equity_slippage_pct=0.0005, # 0.05% slippage
    )
    backtester = Backtester(strategy=strategy, cost_model=cost_model, lot_size=1)

    print("⚙️ Running deterministic backtest loop...")
    result = backtester.run(df, start_date=sim_start_str, end_date=end_str)
    print("✅ Backtest complete!\n")

    # -------------------------------------------------------------
    # PRINT TRADE LOG
    # -------------------------------------------------------------
    print("-" * 105)
    print(" 📋 EXECUTED TRADES (Cross-verify these against your chart)")
    print("-" * 105)
    print(f"{'#':<3} | {'Entry Date':<11} | {'Entry Price':<12} | {'Exit Date':<11} | {'Exit Price':<12} | {'Qty':<4} | {'Gross PnL':<13} | {'Costs':<10} | {'Net PnL':<13} | {'Exit Reason'}")
    print("-" * 105)

    for i, t in enumerate(result.trades, 1):
        entry_d = t.entry_time.strftime("%Y-%m-%d") if t.entry_time else "-"
        exit_d = t.exit_time.strftime("%Y-%m-%d") if t.exit_time else "-"
        gross = f"₹{t.pnl_gross:+,.2f}" if t.pnl_gross is not None else "-"
        costs = f"₹{t.costs.total:,.2f}" if t.costs else "₹0.00"
        net = f"₹{t.pnl_net:+,.2f}" if t.pnl_net is not None else "-"
        exit_p = f"₹{t.exit_price:,.2f}" if t.exit_price else "-"

        print(f"{i:<3} | {entry_d:<11} | {f'₹{t.entry_price:,.2f}':<12} | {exit_d:<11} | {exit_p:<12} | {t.quantity:<4} | {gross:<13} | {costs:<10} | {net:<13} | {t.exit_reason or 'OPEN'}")

    print("-" * 105)

    # -------------------------------------------------------------
    # PRINT PERFORMANCE SUMMARY
    # -------------------------------------------------------------
    m = result.metrics
    print("\n" + "=" * 60)
    print(" 📊 PORTFOLIO PERFORMANCE METRICS (5 YEARS)")
    print("=" * 60)
    metrics_summary = [
        ("Initial Capital", f"₹{m.get('initial_capital', 0):,.2f}"),
        ("Final Equity", f"₹{m.get('final_equity', 0):,.2f}"),
        ("Total Net Profit / Loss", f"₹{m.get('total_pnl', 0):+,.2f}"),
        ("Total Return %", f"{m.get('total_return_pct', 0):+.2f}%"),
        ("CAGR %", f"{m.get('cagr_pct', 0):.2f}%"),
        ("Annualized Volatility", f"{m.get('annualized_volatility_pct', 0):.2f}%"),
        ("Sharpe Ratio (Rf=6.5%)", f"{m.get('sharpe_ratio', 0):.2f}"),
        ("Sortino Ratio", f"{m.get('sortino_ratio', 0):.2f}"),
        ("Maximum Drawdown %", f"{m.get('max_drawdown_pct', 0):.2f}%"),
        ("Max Drawdown Duration", f"{m.get('max_drawdown_duration_days', 0)} days"),
        ("Total Completed Trades", f"{m.get('total_trades', 0)}"),
        ("Winning Trades", f"{m.get('winning_trades', 0)}"),
        ("Losing Trades", f"{m.get('losing_trades', 0)}"),
        ("Win Rate %", f"{m.get('win_rate_pct', 0):.2f}%"),
        ("Profit Factor", f"{m.get('profit_factor', 0):.2f}"),
        ("Total Friction & Taxes Paid", f"₹{result.total_costs:,.2f}"),
    ]
    for label, val in metrics_summary:
        print(f"  {label:<30} : {val}")
    print("=" * 60)


if __name__ == "__main__":
    main()
