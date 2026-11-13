"""
Enhanced Alkem Laboratories 200 SMA Futures Strategy (V2).

Enhancements over Original 200 SMA:
1. ATR Dead-Zone Envelope (1.0x ATR buffer around 200 SMA) to eliminate sideways noise.
2. ADX Trend Strength Gate (ADX > 20) to enforce trading only in active market regimes.
3. Post-Loss Re-Entry Cooldown (8 bars = 2 hours) to break whipsaw streaks.
4. Risk Management: 1.5% Stop Loss and 3.0% Take Profit to bank profits before mean-reversion.
5. Handover: Current month (DTE > 6), Next month (DTE <= 6), Pre-expiry safety exit (DTE <= 1).
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


def get_alkem_200_sma_enhanced_strategy() -> StrategyDefinition:
    """Build the Enhanced Alkem Laboratories 200 SMA 15m Futures strategy definition."""
    sma_200_def = IndicatorDefinition(name="SMA", params={"period": 200, "field": "close"})
    upper_env = IndicatorDefinition(
        name="SMA_ENVELOPE", 
        params={"period": 200, "atr_period": 14, "multiplier": 1.0, "band": "upper"}
    )
    lower_env = IndicatorDefinition(
        name="SMA_ENVELOPE", 
        params={"period": 200, "atr_period": 14, "multiplier": 1.0, "band": "lower"}
    )
    adx_def = IndicatorDefinition(name="ADX", params={"period": 14})

    # Conviction Entries: Beyond ATR dead zone + Active Trend
    close_gt_upper = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=upper_env),
    )
    low_gt_upper = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="low"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=upper_env),
    )
    close_lt_lower = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.LESS_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=lower_env),
    )
    high_lt_lower = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="high"),
        operator=ComparisonOperator.LESS_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=lower_env),
    )

    adx_gate = ConditionNode(
        left_operand=Operand(type=OperandType.INDICATOR, value=adx_def),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.CONSTANT, value=20.0),
    )

    # Exits: Early cross of 200 SMA line
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

    long_exit_signal = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_lt_sma, high_lt_sma],
    )
    short_exit_signal = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[close_gt_sma, low_gt_sma],
    )

    # SET 1: Near-Month Long (DTE > 6)
    set1_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_gt_6, close_gt_upper, low_gt_upper, adx_gate],
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
        leg_stop_loss_pct=0.015,
        leg_target_pct=0.030,
    )
    set1 = StrategySet(
        set_id=1,
        name="Near-Month Long (DTE > 6)",
        entry_conditions=set1_entry,
        legs=[set1_leg],
        exit_conditions=set1_exit,
    )

    # SET 2: Near-Month Short (DTE > 6)
    set2_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_gt_6, close_lt_lower, high_lt_lower, adx_gate],
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
        leg_stop_loss_pct=0.015,
        leg_target_pct=0.030,
    )
    set2 = StrategySet(
        set_id=2,
        name="Near-Month Short (DTE > 6)",
        entry_conditions=set2_entry,
        legs=[set2_leg],
        exit_conditions=set2_exit,
    )

    # SET 3: Next-Month Long (DTE <= 6)
    set3_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_le_6, close_gt_upper, low_gt_upper, adx_gate],
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
        leg_stop_loss_pct=0.015,
        leg_target_pct=0.030,
    )
    set3 = StrategySet(
        set_id=3,
        name="Next-Month Long (DTE <= 6)",
        entry_conditions=set3_entry,
        legs=[set3_leg],
        exit_conditions=set3_exit,
    )

    # SET 4: Next-Month Short (DTE <= 6)
    set4_entry = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[dte_le_6, close_lt_lower, high_lt_lower, adx_gate],
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
        leg_stop_loss_pct=0.015,
        leg_target_pct=0.030,
    )
    set4 = StrategySet(
        set_id=4,
        name="Next-Month Short (DTE <= 6)",
        entry_conditions=set4_entry,
        legs=[set4_leg],
        exit_conditions=set4_exit,
    )

    deployment = DeploymentSettings(
        capital_allocated=500000.0,
        max_daily_loss=25000.0,
        max_trades_per_day=4,
        max_open_positions=1,
        execution_style=ExecutionStyle.POSITIONAL,
        signal_timing=SignalTiming.PREVIOUS_BAR_CLOSE,
        market_open_delay_minutes=0,
        cooldown_bars_after_loss=8,
    )

    return StrategyDefinition(
        id="alkem_200_sma_enhanced_15m",
        name="Alkem Laboratories SMA 200 Enhanced Futures Strategy",
        description="Enhanced with 1.0x ATR Dead-Zone, ADX>20 Gate, 8-bar Cooldown, and 1.5% SL / 3.0% TP",
        author="QuantCopilot",
        underlying="ALKEM",
        timeframe=TimeFrame.M15,
        sets=[set1, set2, set3, set4],
        deployment_settings=deployment,
    )

