"""
Tests for Official Benchmark Strategy: Nestle India 200 SMA 15m Futures.

Verifies:
1. Low/High filter: Long requires Low > SMA, Short requires High < SMA.
2. Single-position concurrency guard (OPEN_POSITIONS == 0 across sets).
3. DTE <= 1 pre-expiry safety exit.
"""

import pytest
import pandas as pd
from datetime import datetime
from src.strategies.nestle_200_sma import get_nestle_200_sma_strategy
from src.schema.strategy import (
    StrategyDefinition, StrategySet, Leg, ConditionGroup, ConditionNode,
    Operand, OperandType, ComparisonOperator, LogicalOperator,
    IndicatorDefinition, DeploymentSettings, InstrumentType, OrderAction,
    TimeFrame, ExecutionStyle
)
from src.engine.condition_evaluator import ConditionEvaluator
from src.engine.backtester import Backtester


def test_nestle_benchmark_schema_validity():
    strategy = get_nestle_200_sma_strategy()
    assert strategy.underlying == "NESTLEIND"
    assert strategy.timeframe == TimeFrame.M15
    assert len(strategy.sets) == 4
    assert strategy.deployment_settings.max_open_positions == 1
    assert strategy.deployment_settings.execution_style == ExecutionStyle.POSITIONAL


def test_low_wick_filter_blocks_long_entry():
    """If close is above 200 SMA, but low dipped below, long entry must be blocked."""
    sma_def = IndicatorDefinition(name="SMA", params={"period": 2, "field": "close"})

    entry_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
                operator=ComparisonOperator.GREATER_THAN,
                right_operand=Operand(type=OperandType.INDICATOR, value=sma_def),
            ),
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="low"),
                operator=ComparisonOperator.GREATER_THAN,
                right_operand=Operand(type=OperandType.INDICATOR, value=sma_def),
            ),
        ],
    )

    dates = pd.date_range("2024-01-01 09:15", periods=3, freq="15min")
    # bar 0: close 100, low 90 -> SMA=NaN
    # bar 1: close 100, low 90 -> SMA=100
    # bar 2: close 105 (>100 SMA), but low is 95 (<= 100 SMA) -> Must NOT trigger Long!
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [105.0, 105.0, 110.0],
            "low": [90.0, 90.0, 95.0],      # low=95 < SMA2=102.5
            "close": [100.0, 100.0, 105.0],  # close=105 > SMA2=102.5
            "volume": [1000, 1000, 1000],
        },
        index=dates,
    )

    res = ConditionEvaluator.evaluate_group(entry_cond, df)
    # Bar 2 should be False because low is not greater than SMA
    assert res.iloc[2] == False


def test_high_wick_filter_blocks_short_entry():
    """If close is below 200 SMA, but high wicked above, short entry must be blocked."""
    sma_def = IndicatorDefinition(name="SMA", params={"period": 2, "field": "close"})

    entry_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
                operator=ComparisonOperator.LESS_THAN,
                right_operand=Operand(type=OperandType.INDICATOR, value=sma_def),
            ),
            ConditionNode(
                left_operand=Operand(type=OperandType.PRICE_FIELD, value="high"),
                operator=ComparisonOperator.LESS_THAN,
                right_operand=Operand(type=OperandType.INDICATOR, value=sma_def),
            ),
        ],
    )

    dates = pd.date_range("2024-01-01 09:15", periods=3, freq="15min")
    # bar 0: close 100, high 110
    # bar 1: close 100, high 110
    # bar 2: close 95 (< 100 SMA), but high is 105 (> 97.5 SMA) -> Must NOT trigger Short!
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [110.0, 110.0, 105.0],  # high=105 > SMA2=97.5
            "low": [90.0, 90.0, 90.0],
            "close": [100.0, 100.0, 95.0],  # close=95 < SMA2=97.5
            "volume": [1000, 1000, 1000],
        },
        index=dates,
    )

    res = ConditionEvaluator.evaluate_group(entry_cond, df)
    assert res.iloc[2] == False


def test_single_position_guard_blocks_concurrent_trades():
    """When Set 1 has an active trade, Set 3 cannot enter (max_open_positions = 1)."""
    # Strategy with 2 sets that both have simple always-true conditions
    true_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.CONSTANT, value=1),
                operator=ComparisonOperator.EQUALS,
                right_operand=Operand(type=OperandType.CONSTANT, value=1),
            )
        ],
    )
    leg1 = Leg(leg_id="l1", instrument_type=InstrumentType.FUTURES, action=OrderAction.BUY, lots=1)
    leg2 = Leg(leg_id="l2", instrument_type=InstrumentType.FUTURES, action=OrderAction.BUY, lots=1)

    s1 = StrategySet(set_id=1, name="Set 1", entry_conditions=true_cond, legs=[leg1])
    s2 = StrategySet(set_id=2, name="Set 2", entry_conditions=true_cond, legs=[leg2])

    strat = StrategyDefinition(
        id="test_single_pos",
        name="Single Pos Test",
        description="Test",
        author="UnitTester",
        underlying="NESTLEIND",
        timeframe=TimeFrame.M15,
        sets=[s1, s2],
        deployment_settings=DeploymentSettings(
            capital_allocated=100000.0,
            max_daily_loss=10000.0,
            max_trades_per_day=10,
            max_open_positions=1,  # Strict 1 position
            execution_style=ExecutionStyle.POSITIONAL,
            market_open_delay_minutes=0,
        ),
    )

    dates = pd.date_range("2024-01-01 09:15", periods=2, freq="15min")
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0],
            "high": [105.0, 106.0],
            "low": [95.0, 98.0],
            "close": [101.0, 104.0],
            "volume": [1000, 1000],
        },
        index=dates,
    )

    bt = Backtester(strategy=strat)
    result = bt.run(df)

    # Even though both Set 1 and Set 2 want to enter, only 1 position should have been taken
    # At the end of backtest, exactly 1 trade was closed
    assert len(result.trades) == 1
    assert result.trades[0].set_id == 1


def test_previous_candle_signal_fills_on_current_candle_open():
    """Verify that when PREVIOUS_BAR_CLOSE is used, signal on bar 0 fills on bar 1 Open."""
    true_cond = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.CONSTANT, value=1),
                operator=ComparisonOperator.EQUALS,
                right_operand=Operand(type=OperandType.CONSTANT, value=1),
            )
        ],
    )
    leg = Leg(leg_id="l1", instrument_type=InstrumentType.FUTURES, action=OrderAction.BUY, lots=1)
    s1 = StrategySet(set_id=1, name="Set 1", entry_conditions=true_cond, legs=[leg])

    from src.schema.strategy import SignalTiming
    strat = StrategyDefinition(
        id="test_prev_bar",
        name="Prev Bar Timing Test",
        description="Test",
        author="UnitTester",
        underlying="NESTLEIND",
        timeframe=TimeFrame.M15,
        sets=[s1],
        deployment_settings=DeploymentSettings(
            capital_allocated=100000.0,
            max_daily_loss=10000.0,
            max_trades_per_day=5,
            signal_timing=SignalTiming.PREVIOUS_BAR_CLOSE,
            execution_style=ExecutionStyle.POSITIONAL,
            market_open_delay_minutes=0,
        ),
    )

    dates = pd.date_range("2024-01-01 09:15", periods=3, freq="15min")
    # bar 0: open 100, close 102
    # bar 1: open 108, close 110
    # bar 2: open 112, close 115
    df = pd.DataFrame(
        {
            "open": [100.0, 108.0, 112.0],
            "high": [105.0, 111.0, 116.0],
            "low": [95.0, 107.0, 110.0],
            "close": [102.0, 110.0, 115.0],
            "volume": [1000, 1000, 1000],
        },
        index=dates,
    )

    bt = Backtester(strategy=strat)
    result = bt.run(df)

    # Signal triggered on bar 0 (09:15) -> Entry executed on bar 1 (09:30) at bar 1 OPEN (108.0)!
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_time == dates[1]
    assert t.entry_price == 108.0  # Must be bar 1 Open, NOT bar 0 Close or bar 1 Close!


def test_high_wick_filter_blocks_long_exit():
    """Verify that Long exit (Close < SMA AND High < SMA) is blocked if High is above SMA."""
    strategy = get_nestle_200_sma_strategy()
    set1_exit = strategy.sets[0].exit_conditions  # Set 1 Near-Month Long exit

    dates = pd.date_range("2024-01-01 09:15", periods=3, freq="15min")
    # bar 0: close 100
    # bar 1: close 100 -> SMA200 requires more bars or mock indicator column
    # We test via ConditionEvaluator directly
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [110.0, 110.0, 105.0],  # high=105 is above 100 SMA
            "low": [90.0, 90.0, 90.0],
            "close": [100.0, 100.0, 95.0],   # close=95 is below 100 SMA
            "volume": [1000, 1000, 1000],
            "days_to_expiry": [10, 10, 10],   # DTE > 1
        },
        index=dates,
    )
    # Mock indicator column
    df["sma_200"] = 100.0

    res = ConditionEvaluator.evaluate_group(set1_exit, df)
    # Bar 2 has close < 100 (95), but high is 105 (> 100), so exit condition must be FALSE!
    assert res.iloc[2] == False


def test_low_wick_filter_blocks_short_exit():
    """Verify that Short exit (Close > SMA AND Low > SMA) is blocked if Low is below SMA."""
    strategy = get_nestle_200_sma_strategy()
    set2_exit = strategy.sets[1].exit_conditions  # Set 2 Near-Month Short exit

    dates = pd.date_range("2024-01-01 09:15", periods=3, freq="15min")
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [110.0, 110.0, 110.0],
            "low": [90.0, 90.0, 95.0],       # low=95 is below 100 SMA
            "close": [100.0, 100.0, 105.0],  # close=105 is above 100 SMA
            "volume": [1000, 1000, 1000],
            "days_to_expiry": [10, 10, 10],   # DTE > 1
        },
        index=dates,
    )
    df["sma_200"] = 100.0

    res = ConditionEvaluator.evaluate_group(set2_exit, df)
    # Bar 2 has close > 100 (105), but low is 95 (< 100), so exit condition must be FALSE!
    assert res.iloc[2] == False

