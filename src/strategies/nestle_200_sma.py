"""
Official Golden Integration Benchmark Strategy: Nestle India 200 SMA Futures Strategy.

Translated directly from Tradetron Strategy ID: 10038358.
Execution rules:
- Long Entry: Close > 200 SMA AND Low > 200 SMA
- Short Entry: Close < 200 SMA AND High < 200 SMA
- Handover: Current month (DTE > 6), Next month (DTE <= 6)
- Safety Exit: DTE <= 1 force exits near-month to prevent physical delivery
- Position Guard: max_open_positions = 1 (OPEN_POSITIONS == 0)
"""

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
    SignalTiming,
    ExpiryType,
)


def get_nestle_200_sma_strategy() -> StrategyDefinition:
    """Build the official Nestle India 200 SMA 15m Futures strategy definition."""
    sma_200_def = IndicatorDefinition(name="SMA", params={"period": 200, "field": "close"})

    # Common condition nodes
    close_gt_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )
    low_gt_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="low"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )
    close_lt_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.LESS_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )
    high_lt_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="high"),
        operator=ComparisonOperator.LESS_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )

    dte_gt_6 = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="days_to_expiry"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.CONSTANT, value=6),
    )
    dte_le_6 = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="days_to_expiry"),
        operator=ComparisonOperator.LESS_EQUAL,
        right_operand=Operand(type=OperandType.CONSTANT, value=6),
    )
    dte_le_1 = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="days_to_expiry"),
        operator=ComparisonOperator.LESS_EQUAL,
        right_operand=Operand(type=OperandType.CONSTANT, value=1),
    )

    # -----------------------------------------------------------------
    # EXIT SIGNALS (Strict Wick Clearance)
    # Long exit: Close < 200 SMA AND High < 200 SMA
    # Short exit: Close > 200 SMA AND Low > 200 SMA
    # -----------------------------------------------------------------
    long_exit_signal = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_lt_sma, high_lt_sma],
    )
    short_exit_signal = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_gt_sma, low_gt_sma],
    )

    # -----------------------------------------------------------------
    # SET 1: Near-Month Long (DTE > 6)
    # -----------------------------------------------------------------
    set1_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_gt_6, close_gt_sma, low_gt_sma],
    )
    set1_exit = ConditionGroup(
        logical_operator=LogicalOperator.OR,
        conditions=[long_exit_signal, dte_le_1],
    )
    set1_leg = Leg(
        leg_id="leg_near_long",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.BUY,
        expiry_type=ExpiryType.MONTHLY,
        lots=1,
    )
    set1 = StrategySet(
        set_id=1,
        name="Near-Month Long (DTE > 6)",
        entry_conditions=set1_entry,
        legs=[set1_leg],
        exit_conditions=set1_exit,
    )

    # -----------------------------------------------------------------
    # SET 2: Near-Month Short (DTE > 6)
    # -----------------------------------------------------------------
    set2_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_gt_6, close_lt_sma, high_lt_sma],
    )
    set2_exit = ConditionGroup(
        logical_operator=LogicalOperator.OR,
        conditions=[short_exit_signal, dte_le_1],
    )
    set2_leg = Leg(
        leg_id="leg_near_short",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.SELL,
        expiry_type=ExpiryType.MONTHLY,
        lots=1,
    )
    set2 = StrategySet(
        set_id=2,
        name="Near-Month Short (DTE > 6)",
        entry_conditions=set2_entry,
        legs=[set2_leg],
        exit_conditions=set2_exit,
    )

    # -----------------------------------------------------------------
    # SET 3: Next-Month Long (DTE <= 6)
    # -----------------------------------------------------------------
    set3_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_le_6, close_gt_sma, low_gt_sma],
    )
    set3_exit = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_lt_sma, high_lt_sma],
    )
    set3_leg = Leg(
        leg_id="leg_next_long",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.BUY,
        expiry_type=ExpiryType.FAR_MONTH,
        lots=1,
    )
    set3 = StrategySet(
        set_id=3,
        name="Next-Month Long (DTE <= 6)",
        entry_conditions=set3_entry,
        legs=[set3_leg],
        exit_conditions=set3_exit,
    )

    # -----------------------------------------------------------------
    # SET 4: Next-Month Short (DTE <= 6)
    # -----------------------------------------------------------------
    set4_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_le_6, close_lt_sma, high_lt_sma],
    )
    set4_exit = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_gt_sma, low_gt_sma],
    )
    set4_leg = Leg(
        leg_id="leg_next_short",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.SELL,
        expiry_type=ExpiryType.FAR_MONTH,
        lots=1,
    )
    set4 = StrategySet(
        set_id=4,
        name="Next-Month Short (DTE <= 6)",
        entry_conditions=set4_entry,
        legs=[set4_leg],
        exit_conditions=set4_exit,
    )

    # -----------------------------------------------------------------
    # DEPLOYMENT SETTINGS
    # -----------------------------------------------------------------
    deployment = DeploymentSettings(
        capital_allocated=500000.0,  # ₹5,00,000 margin for 1 lot futures
        max_daily_loss=25000.0,
        max_trades_per_day=4,
        max_open_positions=1,  # Strict single position guard (OPEN_POSITIONS == 0)
        execution_style=ExecutionStyle.POSITIONAL,
        signal_timing=SignalTiming.PREVIOUS_BAR_CLOSE,  # Previous candle condition -> Current candle open fill
        market_open_delay_minutes=0,  # Allow 09:15 AM market open execution for overnight signals
    )

    return StrategyDefinition(
        id="nestleind_200_sma_15m",
        name="Nestle India SMA 200 Futures Benchmark",
        description="Tradetron 10038358 Dual-Contract Handover on 15m Futures",
        author="Tradetron/QuantCopilot",
        underlying="NESTLEIND",
        timeframe=TimeFrame.M15,
        sets=[set1, set2, set3, set4],
        deployment_settings=deployment,
    )
