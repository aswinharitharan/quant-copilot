"""
Broker Adapter Base Contracts and Pydantic Schemas.

Defines the unified broker interface and standardized data models for orders,
positions, and account balances across PaperBroker and live broker adapters (e.g. Fyers, Angel One).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from src.schema.strategy import InstrumentType, OrderAction, OrderType


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProductType(str, Enum):
    MIS = "MIS"      # Intraday
    NRML = "NRML"    # Normal / Positional Derivatives
    CNC = "CNC"      # Cash & Carry / Delivery Equity


class OrderRequest(BaseModel):
    order_id: Optional[str] = None
    strategy_id: str
    symbol: str
    exchange: str = "NSE"
    instrument_type: InstrumentType = InstrumentType.FUTURES
    action: OrderAction
    order_type: OrderType = OrderType.MARKET
    quantity: int = Field(gt=0, description="Order quantity in units/shares")
    price: Optional[float] = Field(default=None, description="Limit price if order_type is LIMIT")
    trigger_price: Optional[float] = Field(default=None, description="Trigger price if stop order")
    product_type: ProductType = ProductType.NRML
    tag: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class OrderResponse(BaseModel):
    order_id: str
    strategy_id: str
    symbol: str
    status: OrderStatus
    action: OrderAction
    order_type: OrderType
    quantity: int
    filled_quantity: int = 0
    remaining_quantity: int = 0
    average_price: float = 0.0
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class Position(BaseModel):
    symbol: str
    strategy_id: str
    quantity: int = 0  # Positive = Long, Negative = Short, 0 = Flat
    average_entry_price: float = 0.0
    current_price: float = 0.0
    pnl_unrealized: float = 0.0
    pnl_realized: float = 0.0
    product_type: ProductType = ProductType.NRML
    last_updated: datetime = Field(default_factory=datetime.now)


class AccountBalance(BaseModel):
    cash_balance: float
    used_margin: float = 0.0
    available_margin: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_equity: float = 0.0


class BaseBroker(ABC):
    """
    Abstract Broker Adapter interface. Decouples quantitative strategies
    and the Risk Sentinel from specific execution venues.
    """

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        """Fetch current account balance and margin status."""
        pass

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResponse:
        """Place a new order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        pass

    @abstractmethod
    async def modify_order(
        self,
        order_id: str,
        new_price: Optional[float] = None,
        new_quantity: Optional[int] = None,
    ) -> OrderResponse:
        """Modify an existing open order's price or quantity."""
        pass

    @abstractmethod
    async def get_order(self, order_id: str) -> Optional[OrderResponse]:
        """Query status of a specific order."""
        pass

    @abstractmethod
    async def get_open_orders(self, strategy_id: Optional[str] = None) -> List[OrderResponse]:
        """Fetch all open/pending orders, optionally filtered by strategy_id."""
        pass

    @abstractmethod
    async def get_positions(self, strategy_id: Optional[str] = None) -> List[Position]:
        """Fetch all positions, optionally filtered by strategy_id."""
        pass

    @abstractmethod
    async def get_position(self, symbol: str, strategy_id: Optional[str] = None) -> Optional[Position]:
        """Fetch position for a specific symbol and strategy."""
        pass

