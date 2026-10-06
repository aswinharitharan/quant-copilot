from enum import Enum
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, model_validator


# -------------------------------------------------------------------------
# 1. ENUMS & CONSTANTS
# -------------------------------------------------------------------------

class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    CE = "CE"
    PE = "PE"

class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    LIMIT_BUFFER = "LIMIT_BUFFER"

class TimeFrame(str, Enum):
    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"

class StrikeType(str, Enum):
    ATM = "ATM"
    ITM1 = "ITM1"
    ITM2 = "ITM2"
    ITM3 = "ITM3"
    OTM1 = "OTM1"
    OTM2 = "OTM2"
    OTM3 = "OTM3"
    DELTA = "DELTA"
    ABSOLUTE = "ABSOLUTE"

class ExpiryType(str, Enum):
    CURRENT_WEEK = "CURRENT_WEEK"
    NEXT_WEEK = "NEXT_WEEK"
    MONTHLY = "MONTHLY"
    FAR_MONTH = "FAR_MONTH"

class ComparisonOperator(str, Enum):
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_EQUAL = "GREATER_EQUAL"
    LESS_EQUAL = "LESS_EQUAL"
    EQUALS = "EQUALS"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"

class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"

class PositionSizingMode(str, Enum):
    FIXED_LOTS = "FIXED_LOTS"
    FIXED_CAPITAL = "FIXED_CAPITAL"
    PERCENT_EQUITY = "PERCENT_EQUITY"
    RISK_BASED = "RISK_BASED"

class ExpiryRolloverPolicy(str, Enum):
    SQUARE_OFF = "SQUARE_OFF"
    ROLLOVER_NEXT_EXPIRY = "ROLLOVER_NEXT_EXPIRY"

class OperandType(str, Enum):
    INDICATOR = "INDICATOR"
    PRICE_FIELD = "PRICE_FIELD"
    CONSTANT = "CONSTANT"
    TIME_FIELD = "TIME_FIELD"


# -------------------------------------------------------------------------
# 2. OPERANDS & INDICATORS
# -------------------------------------------------------------------------

class IndicatorDefinition(BaseModel):
    name: str = Field(..., description="e.g., EMA, SMA, RSI, VWAP, SUPERTREND")
    params: Dict[str, Any] = Field(default_factory=dict, description="e.g., {'period': 20, 'field': 'close'}")
    timeframe: Optional[TimeFrame] = Field(None, description="Override strategy timeframe for this indicator")

class Operand(BaseModel):
    type: OperandType
    value: Union[IndicatorDefinition, str, float, int] = Field(..., description="Indicator definition, price field like 'close', time like '09:20:00', or constant number")


# -------------------------------------------------------------------------
# 3. CONDITION TREES
# -------------------------------------------------------------------------

class ConditionNode(BaseModel):
    left_operand: Operand
    operator: ComparisonOperator
    right_operand: Operand

class ConditionGroup(BaseModel):
    logical_operator: LogicalOperator = Field(default=LogicalOperator.AND)
    conditions: List[Union[ConditionNode, 'ConditionGroup']]


# -------------------------------------------------------------------------
# 4. LEGS
# -------------------------------------------------------------------------

class Leg(BaseModel):
    leg_id: str
    instrument_type: InstrumentType
    action: OrderAction
    
    # Options specifics
    strike_type: Optional[StrikeType] = None
    strike_offset: Optional[int] = Field(None, description="e.g., +100 for Nifty strikes")
    target_delta: Optional[float] = Field(None, description="e.g., 0.25 delta")
    expiry_type: Optional[ExpiryType] = None
    
    # Sizing and Risk
    lots: int = Field(1, description="Number of lots for F&O, or qty for equity")
    leg_stop_loss_pct: Optional[float] = None
    leg_target_pct: Optional[float] = None
    leg_trailing_sl_pct: Optional[float] = None
    
    @model_validator(mode='after')
    def validate_options_fields(self) -> 'Leg':
        if self.instrument_type in (InstrumentType.CE, InstrumentType.PE):
            if not self.strike_type:
                raise ValueError("strike_type must be specified for Options (CE/PE)")
            if not self.expiry_type:
                raise ValueError("expiry_type must be specified for Options (CE/PE)")
        return self


# -------------------------------------------------------------------------
# 5. STRATEGY SETS
# -------------------------------------------------------------------------

class StrategySet(BaseModel):
    set_id: int
    name: str
    entry_conditions: ConditionGroup
    legs: List[Leg]
    exit_conditions: Optional[ConditionGroup] = None


# -------------------------------------------------------------------------
# 6. DEPLOYMENT SETTINGS
# -------------------------------------------------------------------------

class DeploymentSettings(BaseModel):
    capital_allocated: float = Field(..., description="Capital allocated in base currency (e.g. INR)")
    max_daily_loss: float = Field(..., description="Max daily loss circuit breaker (positive number)")
    max_daily_profit: Optional[float] = None
    max_trades_per_day: int = Field(..., description="Overtrading limiter")
    
    order_type: OrderType = Field(default=OrderType.LIMIT_BUFFER)
    limit_buffer_pct: float = Field(0.005, description="e.g. 0.005 for 0.5% buffer")
    market_open_delay_minutes: int = Field(5, description="Delay from open to start trading")
    intraday_square_off_time: str = Field("15:15:00", description="HH:MM:SS format")
    
    expiry_rollover_policy: ExpiryRolloverPolicy = Field(default=ExpiryRolloverPolicy.SQUARE_OFF)


# -------------------------------------------------------------------------
# 7. ROOT STRATEGY DEFINITION
# -------------------------------------------------------------------------

class StrategyDefinition(BaseModel):
    id: str
    name: str
    description: str
    author: str
    underlying: str = Field(..., description="e.g., 'NIFTY', 'BANKNIFTY'")
    timeframe: TimeFrame
    sets: List[StrategySet]
    universal_exit: Optional[ConditionGroup] = None
    deployment_settings: DeploymentSettings
