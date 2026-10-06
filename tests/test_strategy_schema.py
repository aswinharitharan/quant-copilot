import pytest
import json
from src.schema.strategy import (
    StrategyDefinition, StrategySet, Leg, ConditionGroup, ConditionNode,
    Operand, IndicatorDefinition, DeploymentSettings, InstrumentType,
    OrderAction, StrikeType, ExpiryType, ComparisonOperator, LogicalOperator,
    TimeFrame, OrderType, ExpiryRolloverPolicy, OperandType
)

def test_valid_short_straddle():
    # 9:20 AM Entry Condition
    entry_condition = ConditionGroup(
        logical_operator=LogicalOperator.AND,
        conditions=[
            ConditionNode(
                left_operand=Operand(type=OperandType.TIME_FIELD, value="time"),
                operator=ComparisonOperator.GREATER_EQUAL,
                right_operand=Operand(type=OperandType.CONSTANT, value="09:20:00")
            )
        ]
    )

    # Short ATM Call
    ce_leg = Leg(
        leg_id="leg_1",
        instrument_type=InstrumentType.CE,
        action=OrderAction.SELL,
        strike_type=StrikeType.ATM,
        expiry_type=ExpiryType.CURRENT_WEEK,
        lots=1,
        leg_stop_loss_pct=0.25 # 25% Stop loss on premium
    )

    # Short ATM Put
    pe_leg = Leg(
        leg_id="leg_2",
        instrument_type=InstrumentType.PE,
        action=OrderAction.SELL,
        strike_type=StrikeType.ATM,
        expiry_type=ExpiryType.CURRENT_WEEK,
        lots=1,
        leg_stop_loss_pct=0.25
    )

    # Combine into a Set
    straddle_set = StrategySet(
        set_id=1,
        name="9:20 Short Straddle",
        entry_conditions=entry_condition,
        legs=[ce_leg, pe_leg]
    )

    # Deployment settings
    deployment = DeploymentSettings(
        capital_allocated=100000.0,
        max_daily_loss=3000.0,
        max_trades_per_day=2,
        order_type=OrderType.LIMIT_BUFFER,
        limit_buffer_pct=0.005,
        intraday_square_off_time="15:15:00"
    )

    # Strategy Definition
    strategy = StrategyDefinition(
        id="strat_001",
        name="Classic Intraday Straddle",
        description="Sells ATM CE and PE at 9:20 AM",
        author="QuantCopilot",
        underlying="NIFTY",
        timeframe=TimeFrame.M1,
        sets=[straddle_set],
        deployment_settings=deployment
    )

    assert strategy.id == "strat_001"
    assert len(strategy.sets) == 1
    assert len(strategy.sets[0].legs) == 2
    
    # Check serialization
    json_str = strategy.model_dump_json()
    parsed_dict = json.loads(json_str)
    assert parsed_dict["name"] == "Classic Intraday Straddle"
    assert parsed_dict["deployment_settings"]["max_daily_loss"] == 3000.0

def test_invalid_option_leg_missing_strike():
    with pytest.raises(ValueError, match="strike_type must be specified for Options"):
        Leg(
            leg_id="invalid_1",
            instrument_type=InstrumentType.CE,
            action=OrderAction.BUY,
            expiry_type=ExpiryType.CURRENT_WEEK,
            lots=1
            # Missing strike_type
        )

def test_invalid_option_leg_missing_expiry():
    with pytest.raises(ValueError, match="expiry_type must be specified for Options"):
        Leg(
            leg_id="invalid_2",
            instrument_type=InstrumentType.PE,
            action=OrderAction.BUY,
            strike_type=StrikeType.ATM,
            lots=1
            # Missing expiry_type
        )

def test_json_schema_generation():
    # LLMs need the json schema to know what properties to output
    schema = StrategyDefinition.model_json_schema()
    assert "title" in schema
    assert schema["title"] == "StrategyDefinition"
    assert "properties" in schema
    assert "deployment_settings" in schema["properties"]
