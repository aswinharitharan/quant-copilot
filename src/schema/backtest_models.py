"""
Data models for Backtesting: Trades, Positions, and Results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import pandas as pd
from src.schema.strategy import InstrumentType, OrderAction
from src.engine.costs import TradeCost


@dataclass
class Trade:
    trade_id: str
    set_id: int
    leg_id: str
    instrument_type: InstrumentType
    action: OrderAction  # BUY or SELL
    entry_time: datetime
    entry_price: float
    quantity: int
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    costs: Optional[TradeCost] = None
    pnl_gross: Optional[float] = None
    pnl_net: Optional[float] = None


@dataclass
class BacktestResult:
    strategy_id: str
    strategy_name: str
    underlying: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    trades: List[Trade]
    equity_curve: pd.Series
    metrics: Dict[str, Any] = field(default_factory=dict)
    total_costs: float = 0.0
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
