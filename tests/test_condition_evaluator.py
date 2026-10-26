import pytest
import pandas as pd
from src.schema.strategy import (
    ConditionGroup,
    ConditionNode,
    Operand,
    OperandType,
    ComparisonOperator,
    LogicalOperator,
    IndicatorDefinition,
)
from src.engine.condition_evaluator import ConditionEvaluator


@pytest.fixture
def sample_df():
    dates = pd.date_range("2024-01-01 09:15", periods=6, freq="15min")
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 103.0, 106.0, 108.0],
            "high": [103.0, 105.0, 106.0, 105.0, 108.0, 110.0],
            "low": [99.0, 101.0, 102.0, 101.0, 105.0, 107.0],
            "close": [101.0, 103.0, 105.0, 102.0, 107.0, 109.0],
            "volume": [1000, 1200, 1500, 800, 2000, 2500],
        },
        index=dates,
    )


def test_simple_greater_than(sample_df):
    node = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.CONSTANT, value=104.0),
    )
    res = ConditionEvaluator.evaluate_node(node, sample_df)
    # close: [101, 103, 105, 102, 107, 109]
    # > 104: [F, F, T, F, T, T]
    expected = [False, False, True, False, True, True]
    assert list(res.values) == expected


def test_crosses_above(sample_df):
    # Crosses above constant 104.0
    # prev bar <= 104 and curr bar > 104
    # close: [101, 103, 105, 102, 107, 109]
    # bar 2 (105): prev is 103 (<=104), curr is 105 (>104) -> CROSSES_ABOVE = True
    # bar 3 (102): curr <= 104 -> False
    # bar 4 (107): prev is 102 (<=104), curr is 107 (>104) -> CROSSES_ABOVE = True
    # bar 5 (109): prev is 107 (>104), so not a crossing -> False
    node = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.CROSSES_ABOVE,
        right_operand=Operand(type=OperandType.CONSTANT, value=104.0),
    )
    res = ConditionEvaluator.evaluate_node(node, sample_df)
    expected = [False, False, True, False, True, False]
    assert list(res.values) == expected


def test_time_gate_condition(sample_df):
    # Time >= 09:30:00
    # Times: 09:15, 09:30, 09:45, 10:00, 10:15, 10:30
    node = ConditionNode(
        left_operand=Operand(type=OperandType.TIME_FIELD, value="time"),
        operator=ComparisonOperator.GREATER_EQUAL,
        right_operand=Operand(type=OperandType.TIME_FIELD, value="09:30:00"),
    )
    res = ConditionEvaluator.evaluate_node(node, sample_df)
    expected = [False, True, True, True, True, True]
    assert list(res.values) == expected


def test_condition_group_and(sample_df):
    cond1 = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.CONSTANT, value=104.0),
    )
    cond2 = ConditionNode(
        left_operand=Operand(type=OperandType.TIME_FIELD, value="time"),
        operator=ComparisonOperator.GREATER_EQUAL,
        right_operand=Operand(type=OperandType.TIME_FIELD, value="10:00:00"),
    )
    group = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[cond1, cond2],
    )
    # close > 104: [F, F, T, F, T, T]
    # time >= 10:00: [F, F, F, T, T, T]
    # AND: [F, F, F, F, T, T]
    res = ConditionEvaluator.evaluate_group(group, sample_df)
    expected = [False, False, False, False, True, True]
    assert list(res.values) == expected


def test_indicator_condition(sample_df):
    # SMA 2 on close:
    # close: [101, 103, 105, 102, 107, 109]
    # sma2:  [NaN, 102, 104, 103.5, 104.5, 108]
    # close > sma2:
    # bar 0: F (NaN)
    # bar 1: 103 > 102 -> T
    # bar 2: 105 > 104 -> T
    # bar 3: 102 > 103.5 -> F
    # bar 4: 107 > 104.5 -> T
    # bar 5: 109 > 108 -> T
    node = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(
            type=OperandType.INDICATOR,
            value=IndicatorDefinition(name="SMA", params={"period": 2, "field": "close"}),
        ),
    )
    res = ConditionEvaluator.evaluate_node(node, sample_df)
    expected = [False, True, True, False, True, True]
    assert list(res.values) == expected
