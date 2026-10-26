import pytest
import pandas as pd
from datetime import datetime
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
from src.engine.backtester import Backtester
from src.engine.costs import TransactionCostModel


def build_sma_strategy(execution_style=ExecutionStyle.INTRADAY, max_trades=2, max_loss=5000.0):
    entry_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
                operator=ComparisonOperator.CROSSES_ABOVE,
                right_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="SMA", params={"period": 2, "field": "close"}),
                ),
            )
        ],
    )
    exit_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
                operator=ComparisonOperator.CROSSES_BELOW,
                right_operand=Operand(
                    type=OperandType.INDICATOR,
                    value=IndicatorDefinition(name="SMA", params={"period": 2, "field": "close"}),
                ),
            )
        ],
    )
    leg = Leg(
        leg_id="l1",
        instrument_type=InstrumentType.EQUITY,
        action=OrderAction.BUY,
        lots=10,
    )
    strat_set = StrategySet(
        set_id=1,
        name="SMA Set",
        entry_conditions=entry_cond,
        legs=[leg],
        exit_conditions=exit_cond,
    )
    deploy = DeploymentSettings(
        capital_allocated=100000.0,
        max_daily_loss=max_loss,
        max_trades_per_day=max_trades,
        execution_style=execution_style,
        market_open_delay_minutes=0,
    )
    return StrategyDefinition(
        id="test_sma",
        name="Test SMA",
        description="Test",
        author="UnitTester",
        underlying="NESTLEIND",
        timeframe=TimeFrame.M15,
        sets=[strat_set],
        deployment_settings=deploy,
    )


def test_backtester_sma_crossover():
    strategy = build_sma_strategy(execution_style=ExecutionStyle.INTRADAY)
    dates = pd.date_range("2024-01-01 09:15", periods=6, freq="15min")
    # close: [100, 95, 105, 110, 90, 85]
    # SMA2:  [NaN, 97.5, 100, 107.5, 100, 87.5]
    # bar 2 (105): crosses above 100 -> BUY
    # bar 4 (90): crosses below 100 -> SELL
    df = pd.DataFrame(
        {
            "open": [100.0, 96.0, 98.0, 106.0, 108.0, 88.0],
            "high": [102.0, 97.0, 106.0, 112.0, 109.0, 89.0],
            "low": [98.0, 94.0, 97.0, 104.0, 89.0, 84.0],
            "close": [100.0, 95.0, 105.0, 110.0, 90.0, 85.0],
            "volume": [1000] * 6,
        },
        index=dates,
    )

    bt = Backtester(strategy=strategy, lot_size=1)
    result = bt.run(df)

    assert len(result.trades) >= 1
    t = result.trades[0]
    assert t.entry_price == 105.0
    assert t.exit_price == 90.0
    assert t.exit_reason == "SET_EXIT_CONDITION"
    assert result.initial_capital == 100000.0
    assert result.metrics["total_trades"] >= 1


def test_backtester_intraday_square_off():
    strategy = build_sma_strategy(execution_style=ExecutionStyle.INTRADAY)
    dates = pd.date_range("2024-01-01 14:00", "2024-01-01 15:30", freq="15min")
    # Bars: 14:00, 14:15, 14:30, 14:45, 15:00, 15:15, 15:30
    # bar 0: 100 -> SMA2=NaN
    # bar 1: 95  -> SMA2=97.5 (close <= SMA)
    # bar 2: 105 -> SMA2=100.0 (close > SMA -> crosses above!)
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 105.0,
            "low": 90.0,
            "close": [100.0, 95.0, 105.0, 110.0, 112.0, 115.0, 116.0],
            "volume": 1000,
        },
        index=dates,
    )
    bt = Backtester(strategy=strategy, lot_size=1)
    result = bt.run(df)

    # Position entered at 14:30 (bar 2), exited at 15:15 due to square off
    square_off_trades = [t for t in result.trades if t.exit_reason == "INTRADAY_SQUARE_OFF"]
    assert len(square_off_trades) == 1
    assert square_off_trades[0].exit_time == pd.to_datetime("2024-01-01 15:15:00")


def test_backtester_positional_holds_overnight():
    strategy = build_sma_strategy(execution_style=ExecutionStyle.POSITIONAL)
    # Day 1 ends at 15:30, Day 2 starts at 09:15
    day1 = pd.date_range("2024-01-01 14:00", "2024-01-01 15:30", freq="15min")
    day2 = pd.date_range("2024-01-02 09:15", "2024-01-02 10:30", freq="15min")
    dates = day1.append(day2)

    # bar 0: 100, bar 1: 95 (close <= SMA2 97.5), bar 2: 105 (crosses above)
    close_prices = [100.0, 95.0, 105.0] + [105.0] * (len(dates) - 3)
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 105.0,
            "low": 90.0,
            "close": close_prices,
            "volume": 1000,
        },
        index=dates,
    )
    bt = Backtester(strategy=strategy, lot_size=1)
    result = bt.run(df)

    # Should NOT have any INTRADAY_SQUARE_OFF
    square_offs = [t for t in result.trades if t.exit_reason == "INTRADAY_SQUARE_OFF"]
    assert len(square_offs) == 0
    # Final trade closed at END_OF_BACKTEST on day 2
    assert result.trades[-1].exit_reason == "END_OF_BACKTEST"
    assert result.trades[-1].exit_time == dates[-1]
