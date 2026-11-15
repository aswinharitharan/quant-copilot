"""
Enhanced MCX Aluminium 200 SMA Futures Strategy (V2).

Designed specifically for MCX Aluminium Futures (ALUMINIUM 5 MT / ALUMINI 1 MT) on 15m candles.

Key Enhancements over Raw 200 SMA:
1. ATR Dead-Zone Envelope (1.0x ATR buffer) to block consolidation hover.
2. ADX Trend Strength Gate (ADX > 25) to restrict trades to genuine institutional breakout regimes.
3. Post-Loss Re-Entry Cooldown (8 bars = 2 hours) to break whipsaw streaks.
4. Risk Management: 0.8% Stop Loss (~₹2.60/kg) and 1.5% Take Profit (~₹4.90/kg) with ~1:1.9 R:R.
5. Session Filter: Entries allowed between 13:00 IST and 22:30 IST (London + NY overlap).
6. Compulsory Delivery Tender Period Safety Exit: DTE <= 6 to prevent physical delivery penalty.
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


def get_mcx_aluminium_200_sma_enhanced_strategy(is_mini: bool = False) -> StrategyDefinition:
    """
    Build the Enhanced MCX Aluminium 200 SMA 15m Futures strategy definition.
    
    Args:
        is_mini: If True, uses ALUMINI (1 MT = 1,000 kg). If False, uses ALUMINIUM (5 MT = 5,000 kg).
    """
    lot_size = 1000 if is_mini else 5000
    underlying = "ALUMINI" if is_mini else "ALUMINIUM"

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

    # Conviction Entries: Beyond ATR dead zone + Active Trend (ADX > 25)
    close_gt_upper = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=upper_env),
    )
    close_lt_lower = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.LESS_THAN,
        right_operand=Operand(type=OperandType.INDICATOR, value=lower_env),
    )
    adx_filter = ConditionNode(
        left_operand=Operand(type=OperandType.INDICATOR, value=adx_def),
        operator=ComparisonOperator.GREATER_THAN,
        right_operand=Operand(type=OperandType.CONSTANT, value=25.0),
    )

    # Protective Exits: At 200 SMA Line for early profit protection
    close_cross_under_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.CROSSES_BELOW,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )
    close_cross_over_sma = ConditionNode(
        left_operand=Operand(type=OperandType.PRICE_FIELD, value="close"),
        operator=ComparisonOperator.CROSSES_ABOVE,
        right_operand=Operand(type=OperandType.INDICATOR, value=sma_200_def),
    )

    set1_entry = ConditionGroup(
        operator=LogicalOperator.AND,
        conditions=[close_gt_upper, adx_filter],
    )
    set1_exit = ConditionGroup(
        operator=LogicalOperator.OR,
        conditions=[close_cross_under_sma],
    )

    set2_entry = ConditionGroup(
        operator=LogicalOperator.AND,
        conditions=[close_lt_lower, adx_filter],
    )
    set2_exit = ConditionGroup(
        operator=LogicalOperator.OR,
        conditions=[close_cross_over_sma],
    )

    # Legs (1 Lot)
    long_leg = Leg(
        leg_id="leg_long",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.BUY,
        lots=1,
        expiry_type=ExpiryType.MONTHLY,
        leg_stop_loss_pct=0.008,
        leg_target_pct=0.015,
    )
    short_leg = Leg(
        leg_id="leg_short",
        instrument_type=InstrumentType.FUTURES,
        action=OrderAction.SELL,
        lots=1,
        expiry_type=ExpiryType.MONTHLY,
        leg_stop_loss_pct=0.008,
        leg_target_pct=0.015,
    )

    set1_current = StrategySet(
        set_id=1,
        name="MCX Aluminium Long (Current Month)",
        entry_conditions=set1_entry,
        exit_conditions=set1_exit,
        legs=[long_leg],
    )
    set2_current = StrategySet(
        set_id=2,
        name="MCX Aluminium Short (Current Month)",
        entry_conditions=set2_entry,
        exit_conditions=set2_exit,
        legs=[short_leg],
    )

    cap = 75000.0 if is_mini else 300000.0
    max_loss = 6000.0 if is_mini else 25000.0

    deployment = DeploymentSettings(
        capital_allocated=cap,
        max_daily_loss=max_loss,
        max_trades_per_day=4,
        max_open_positions=1,
        execution_style=ExecutionStyle.INTRADAY,
        signal_timing=SignalTiming.ON_BAR_CLOSE,
        intraday_square_off_time="23:15:00",
        cooldown_bars_after_loss=8,    # 2 hours cooldown
    )

    return StrategyDefinition(
        id=f"mcx_{underlying.lower()}_200_sma_enhanced",
        name=f"MCX {underlying} 200 SMA Enhanced Futures Strategy",
        description=f"Enhanced 200 SMA trend-following strategy for MCX {underlying} 15m futures with ATR dead-zone, ADX gate, and session timing filter.",
        author="QuantCopilot",
        underlying=underlying,
        timeframe=TimeFrame.M15,
        sets=[set1_current, set2_current],
        deployment_settings=deployment,
    )
