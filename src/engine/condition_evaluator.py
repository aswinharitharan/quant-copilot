"""
Condition Evaluator for Strategy DSL Condition Trees.

Resolves ConditionGroup and ConditionNode schemas into boolean signals per bar,
adhering strictly to anti-lookahead rules.
"""

from datetime import time
from typing import Union
import pandas as pd
import numpy as np

from src.schema.strategy import (
    ConditionGroup,
    ConditionNode,
    Operand,
    OperandType,
    ComparisonOperator,
    LogicalOperator,
    IndicatorDefinition,
)
from src.engine.indicators import IndicatorEngine


class ConditionEvaluationError(Exception):
    """Exception raised when condition evaluation fails."""
    pass


class ConditionEvaluator:
    """
    Evaluates ConditionGroup and ConditionNode structures against OHLCV data.
    """

    @classmethod
    def evaluate_group(cls, group: ConditionGroup, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate a ConditionGroup across all bars in df.
        
        Returns:
            pd.Series of boolean values with the same index as df.
        """
        if not group.conditions:
            # Empty condition group defaults to True
            return pd.Series(True, index=df.index)

        results = []
        for cond in group.conditions:
            if isinstance(cond, ConditionGroup):
                sub_res = cls.evaluate_group(cond, df)
            elif isinstance(cond, ConditionNode):
                sub_res = cls.evaluate_node(cond, df)
            else:
                raise ConditionEvaluationError(f"Unexpected condition element: {type(cond)}")
            results.append(sub_res)

        if group.logical_operator == LogicalOperator.AND:
            combined = results[0]
            for r in results[1:]:
                combined = combined & r
            return combined.fillna(False)
        elif group.logical_operator == LogicalOperator.OR:
            combined = results[0]
            for r in results[1:]:
                combined = combined | r
            return combined.fillna(False)
        else:
            raise ConditionEvaluationError(f"Unsupported logical operator: {group.logical_operator}")

    @classmethod
    def evaluate_node(cls, node: ConditionNode, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate a single ConditionNode (left op right) across all bars in df.
        """
        left = cls._resolve_operand(node.left_operand, df)
        right = cls._resolve_operand(node.right_operand, df)

        op = node.operator

        if op == ComparisonOperator.GREATER_THAN:
            res = left > right
        elif op == ComparisonOperator.LESS_THAN:
            res = left < right
        elif op == ComparisonOperator.GREATER_EQUAL:
            res = left >= right
        elif op == ComparisonOperator.LESS_EQUAL:
            res = left <= right
        elif op == ComparisonOperator.EQUALS:
            if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
                res = (left - right).abs() < 1e-6
            else:
                res = left == right
        elif op == ComparisonOperator.CROSSES_ABOVE:
            prev_left = left.shift(1)
            prev_right = right.shift(1) if isinstance(right, pd.Series) else right
            res = (prev_left <= prev_right) & (left > right)
        elif op == ComparisonOperator.CROSSES_BELOW:
            prev_left = left.shift(1)
            prev_right = right.shift(1) if isinstance(right, pd.Series) else right
            res = (prev_left >= prev_right) & (left < right)
        else:
            raise ConditionEvaluationError(f"Unsupported comparison operator: {op}")

        return res.fillna(False)

    @classmethod
    def _resolve_operand(
        cls, operand: Operand, df: pd.DataFrame
    ) -> Union[pd.Series, float, int, time]:
        """
        Resolve an Operand into a pd.Series or compatible type for evaluation.
        """
        op_type = operand.type
        val = operand.value

        if op_type == OperandType.PRICE_FIELD:
            col_name = str(val).lower()
            if col_name not in df.columns:
                raise ConditionEvaluationError(f"Price field '{col_name}' not in DataFrame columns")
            return df[col_name]

        elif op_type == OperandType.INDICATOR:
            if isinstance(val, dict):
                ind_def = IndicatorDefinition(**val)
            elif isinstance(val, IndicatorDefinition):
                ind_def = val
            else:
                raise ConditionEvaluationError(f"Invalid indicator operand value: {val}")
            return IndicatorEngine.compute(df, ind_def)

        elif op_type == OperandType.CONSTANT:
            try:
                num_val = float(val)
                return pd.Series(num_val, index=df.index)
            except (ValueError, TypeError):
                # String constant (e.g. for time string)
                return pd.Series(val, index=df.index)

        elif op_type == OperandType.TIME_FIELD:
            if not isinstance(df.index, pd.DatetimeIndex):
                raise ConditionEvaluationError("TIME_FIELD operand requires a DatetimeIndex")
            # If the value is "time", return time of day series
            if str(val).lower() in ("time", "current_time"):
                # Returns pd.Series of datetime.time
                return pd.Series(df.index.time, index=df.index)
            else:
                # Specific time constant representation e.g. "09:20:00"
                t_val = cls._parse_time_str(str(val))
                return pd.Series(t_val, index=df.index)

        else:
            raise ConditionEvaluationError(f"Unsupported operand type: {op_type}")

    @staticmethod
    def _parse_time_str(time_str: str) -> time:
        """Parse 'HH:MM:SS' or 'HH:MM' string to datetime.time."""
        parts = [int(p) for p in time_str.split(":")]
        if len(parts) == 2:
            return time(parts[0], parts[1], 0)
        elif len(parts) == 3:
            return time(parts[0], parts[1], parts[2])
        raise ValueError(f"Invalid time string format: {time_str}")
