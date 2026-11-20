"""
PaperBroker: High-fidelity virtual execution engine.

Simulates order matching, margin accounting, slippage, and Indian statutory transaction
costs against live WebSocket ticks or historical candle bars without real financial risk.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.brokers.base import (
    AccountBalance,
    BaseBroker,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    Position,
    ProductType,
)
from src.engine.costs import TransactionCostModel
from src.schema.strategy import InstrumentType, OrderAction, OrderType


class PaperBroker(BaseBroker):
    """
    Virtual order execution and portfolio ledger simulation engine.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        default_margin_pct: float = 0.20,  # 20% margin for derivatives (NRML/MIS)
        slippage_pct: float = 0.0005,       # 0.05% realistic slippage
        cost_model: Optional[TransactionCostModel] = None,
        fixed_margins: Optional[Dict[str, float]] = None,
    ):
        self.initial_capital = initial_capital
        self.cash_balance = initial_capital
        self.default_margin_pct = default_margin_pct
        self.slippage_pct = slippage_pct
        self.cost_model = cost_model or TransactionCostModel()
        self.fixed_margins = fixed_margins or {}  # e.g. {"MCX:ALUMINIUM": 75000.0}

        # Internal state
        self._orders: Dict[str, OrderResponse] = {}
        self._order_requests: Dict[str, OrderRequest] = {}
        self._positions: Dict[Tuple[str, str], Position] = {}  # key: (symbol, strategy_id)
        self._current_prices: Dict[str, float] = {}
        self._realized_pnl: float = 0.0
        self._total_costs: float = 0.0

    # -------------------------------------------------------------------------
    # Market Data Feeds (Tick / Bar ingestion)
    # -------------------------------------------------------------------------

    def on_tick(self, symbol: str, ltp: float, timestamp: Optional[datetime] = None) -> List[OrderResponse]:
        """
        Ingest a live tick, update mark-to-market valuations, and match pending limit orders.
        """
        now = timestamp or datetime.now()
        self._current_prices[symbol] = ltp

        # 1. Update mark-to-market unrealized PnL on open positions
        for (pos_sym, _), pos in self._positions.items():
            if pos_sym == symbol and pos.quantity != 0:
                pos.current_price = ltp
                if pos.quantity > 0:  # Long
                    pos.pnl_unrealized = (ltp - pos.average_entry_price) * pos.quantity
                else:  # Short
                    pos.pnl_unrealized = (pos.average_entry_price - ltp) * abs(pos.quantity)
                pos.last_updated = now

        # 2. Check and match open limit orders for this symbol
        filled_orders: List[OrderResponse] = []
        for order_id, order in list(self._orders.items()):
            if order.symbol == symbol and order.status in (OrderStatus.OPEN, OrderStatus.PENDING):
                request = self._order_requests[order_id]
                if request.order_type == OrderType.LIMIT and request.price is not None:
                    if request.action == OrderAction.BUY and ltp <= request.price:
                        fill_price = min(ltp, request.price) * (1.0 + self.slippage_pct)
                        self._execute_fill(order_id, fill_price, now)
                        filled_orders.append(self._orders[order_id])
                    elif request.action == OrderAction.SELL and ltp >= request.price:
                        fill_price = max(ltp, request.price) * (1.0 - self.slippage_pct)
                        self._execute_fill(order_id, fill_price, now)
                        filled_orders.append(self._orders[order_id])

        return filled_orders

    def on_bar(
        self,
        symbol: str,
        open_: float,
        high: float,
        low: float,
        close: float,
        timestamp: Optional[datetime] = None,
    ) -> List[OrderResponse]:
        """
        Ingest a completed candle bar. Matches limit orders within the bar's High/Low extremes.
        """
        now = timestamp or datetime.now()
        filled_orders: List[OrderResponse] = []

        # Check limit orders against bar bounds
        for order_id, order in list(self._orders.items()):
            if order.symbol == symbol and order.status in (OrderStatus.OPEN, OrderStatus.PENDING):
                request = self._order_requests[order_id]
                if request.order_type == OrderType.LIMIT and request.price is not None:
                    if request.action == OrderAction.BUY and low <= request.price:
                        # Filled at limit or open (whichever was lower)
                        fill_base = min(open_, request.price) if open_ <= request.price else request.price
                        fill_price = fill_base * (1.0 + self.slippage_pct)
                        self._execute_fill(order_id, fill_price, now)
                        filled_orders.append(self._orders[order_id])
                    elif request.action == OrderAction.SELL and high >= request.price:
                        # Filled at limit or open (whichever was higher)
                        fill_base = max(open_, request.price) if open_ >= request.price else request.price
                        fill_price = fill_base * (1.0 - self.slippage_pct)
                        self._execute_fill(order_id, fill_price, now)
                        filled_orders.append(self._orders[order_id])

        # Update final price on close
        self.on_tick(symbol, close, now)
        return filled_orders

    # -------------------------------------------------------------------------
    # BaseBroker Implementation
    # -------------------------------------------------------------------------

    async def get_balance(self) -> AccountBalance:
        used_margin = self._calculate_used_margin()
        unrealized_pnl = sum(p.pnl_unrealized for p in self._positions.values())
        total_equity = self.cash_balance + unrealized_pnl
        available_margin = max(0.0, total_equity - used_margin)

        return AccountBalance(
            cash_balance=round(self.cash_balance, 2),
            used_margin=round(used_margin, 2),
            available_margin=round(available_margin, 2),
            realized_pnl=round(self._realized_pnl, 2),
            unrealized_pnl=round(unrealized_pnl, 2),
            total_equity=round(total_equity, 2),
        )

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        order_id = request.order_id or f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now()

        # Determine current market price and reference price for margin
        market_price = self._current_prices.get(request.symbol)
        ref_price = market_price or request.price
        if ref_price is None or ref_price <= 0:
            resp = OrderResponse(
                order_id=order_id,
                strategy_id=request.strategy_id,
                symbol=request.symbol,
                status=OrderStatus.REJECTED,
                action=request.action,
                order_type=request.order_type,
                quantity=request.quantity,
                message="Rejected: No market price available for symbol",
                timestamp=now,
            )
            self._orders[order_id] = resp
            return resp

        # Margin check for orders that increase position exposure
        required_margin = self._calculate_order_margin(request, ref_price)
        current_balance = await self.get_balance()
        if required_margin > current_balance.available_margin:
            resp = OrderResponse(
                order_id=order_id,
                strategy_id=request.strategy_id,
                symbol=request.symbol,
                status=OrderStatus.REJECTED,
                action=request.action,
                order_type=request.order_type,
                quantity=request.quantity,
                message=(
                    f"Insufficient margin: Required ₹{required_margin:.2f}, "
                    f"Available ₹{current_balance.available_margin:.2f}"
                ),
                timestamp=now,
            )
            self._orders[order_id] = resp
            return resp

        # Create Open order record
        resp = OrderResponse(
            order_id=order_id,
            strategy_id=request.strategy_id,
            symbol=request.symbol,
            status=OrderStatus.OPEN,
            action=request.action,
            order_type=request.order_type,
            quantity=request.quantity,
            remaining_quantity=request.quantity,
            timestamp=now,
        )
        self._orders[order_id] = resp
        self._order_requests[order_id] = request

        # Immediate fill evaluation for MARKET or marketable LIMIT orders
        if request.order_type == OrderType.MARKET:
            fill_price = (
                ref_price * (1.0 + self.slippage_pct)
                if request.action == OrderAction.BUY
                else ref_price * (1.0 - self.slippage_pct)
            )
            self._execute_fill(order_id, fill_price, now)
        elif request.order_type == OrderType.LIMIT and request.price is not None and market_price is not None:
            # Marketable limit check against current market price
            if request.action == OrderAction.BUY and market_price <= request.price:
                fill_price = min(market_price, request.price) * (1.0 + self.slippage_pct)
                self._execute_fill(order_id, fill_price, now)
            elif request.action == OrderAction.SELL and market_price >= request.price:
                fill_price = max(market_price, request.price) * (1.0 - self.slippage_pct)
                self._execute_fill(order_id, fill_price, now)

        return self._orders[order_id]

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order and order.status in (OrderStatus.OPEN, OrderStatus.PENDING):
            order.status = OrderStatus.CANCELLED
            order.message = "Cancelled by user"
            return True
        return False

    async def modify_order(
        self,
        order_id: str,
        new_price: Optional[float] = None,
        new_quantity: Optional[int] = None,
    ) -> OrderResponse:
        order = self._orders.get(order_id)
        if not order or order.status not in (OrderStatus.OPEN, OrderStatus.PENDING):
            raise ValueError(f"Cannot modify order {order_id} in status {order.status if order else 'NOT_FOUND'}")

        req = self._order_requests[order_id]
        if new_price is not None:
            req.price = new_price
        if new_quantity is not None:
            req.quantity = new_quantity
            order.quantity = new_quantity
            order.remaining_quantity = new_quantity

        # Re-check execution if marketable
        if req.price is not None and req.symbol in self._current_prices:
            ltp = self._current_prices[req.symbol]
            if req.action == OrderAction.BUY and ltp <= req.price:
                self._execute_fill(order_id, ltp * (1.0 + self.slippage_pct), datetime.now())
            elif req.action == OrderAction.SELL and ltp >= req.price:
                self._execute_fill(order_id, ltp * (1.0 - self.slippage_pct), datetime.now())

        return self._orders[order_id]

    async def get_order(self, order_id: str) -> Optional[OrderResponse]:
        return self._orders.get(order_id)

    async def get_open_orders(self, strategy_id: Optional[str] = None) -> List[OrderResponse]:
        orders = [o for o in self._orders.values() if o.status in (OrderStatus.OPEN, OrderStatus.PENDING)]
        if strategy_id:
            orders = [o for o in orders if o.strategy_id == strategy_id]
        return orders

    async def get_positions(self, strategy_id: Optional[str] = None) -> List[Position]:
        positions = [p for p in self._positions.values() if p.quantity != 0]
        if strategy_id:
            positions = [p for p in positions if p.strategy_id == strategy_id]
        return positions

    async def get_position(self, symbol: str, strategy_id: Optional[str] = None) -> Optional[Position]:
        strat_id = strategy_id or ""
        key = (symbol, strat_id)
        if key in self._positions:
            pos = self._positions[key]
            if pos.quantity != 0:
                return pos
        # Search if strategy_id not specified
        for (pos_sym, _), pos in self._positions.items():
            if pos_sym == symbol and pos.quantity != 0:
                return pos
        return None

    # -------------------------------------------------------------------------
    # Internal Accounting & Position Lifecycle
    # -------------------------------------------------------------------------

    def _execute_fill(self, order_id: str, fill_price: float, timestamp: datetime) -> None:
        fill_price = round(fill_price, 2)
        order = self._orders[order_id]
        request = self._order_requests[order_id]
        qty = request.quantity

        order.status = OrderStatus.FILLED
        order.filled_quantity = qty
        order.remaining_quantity = 0
        order.average_price = fill_price
        order.timestamp = timestamp

        # Compute and deduct transaction friction (STT, Exchange fees, GST, SEBI, Slippage)
        costs = self.cost_model.calculate(
            action=request.action,
            instrument_type=request.instrument_type,
            price=fill_price,
            quantity=qty,
            is_intraday=(request.product_type == ProductType.MIS),
        )
        self.cash_balance -= costs.total
        self._total_costs += costs.total
        self._current_prices[request.symbol] = fill_price

        # Update position
        key = (request.symbol, request.strategy_id)
        pos = self._positions.get(key)
        if pos is None:
            pos = Position(
                symbol=request.symbol,
                strategy_id=request.strategy_id,
                quantity=0,
                average_entry_price=0.0,
                current_price=fill_price,
                product_type=request.product_type,
                last_updated=timestamp,
            )
            self._positions[key] = pos

        order_delta = qty if request.action == OrderAction.BUY else -qty
        old_qty = pos.quantity
        new_qty = old_qty + order_delta

        if old_qty == 0:
            # New opening position
            pos.quantity = new_qty
            pos.average_entry_price = fill_price
            pos.pnl_unrealized = 0.0
        elif (old_qty > 0 and order_delta > 0) or (old_qty < 0 and order_delta < 0):
            # Adding to existing position in the same direction
            total_cost = (abs(old_qty) * pos.average_entry_price) + (abs(order_delta) * fill_price)
            pos.quantity = new_qty
            pos.average_entry_price = round(total_cost / abs(new_qty), 2)
        else:
            # Reducing, closing, or flipping position
            closed_qty = min(abs(old_qty), abs(order_delta))
            if old_qty > 0:  # Was Long, selling to close
                trade_pnl = (fill_price - pos.average_entry_price) * closed_qty
            else:  # Was Short, buying to cover
                trade_pnl = (pos.average_entry_price - fill_price) * closed_qty

            self._realized_pnl += trade_pnl
            self.cash_balance += trade_pnl
            pos.pnl_realized += trade_pnl

            pos.quantity = new_qty
            if new_qty == 0:
                pos.average_entry_price = 0.0
                pos.pnl_unrealized = 0.0
            elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                # Flipped position
                pos.average_entry_price = fill_price
                pos.pnl_unrealized = 0.0

        pos.current_price = fill_price
        pos.last_updated = timestamp

    def _calculate_used_margin(self) -> float:
        used = 0.0
        for (symbol, _), pos in self._positions.items():
            if pos.quantity != 0:
                price = self._current_prices.get(symbol, pos.average_entry_price)
                if pos.product_type == ProductType.CNC:
                    used += abs(pos.quantity) * price
                elif symbol in self.fixed_margins:
                    used += self.fixed_margins[symbol]
                else:
                    used += abs(pos.quantity) * price * self.default_margin_pct
        return used

    def _calculate_order_margin(self, request: OrderRequest, ref_price: float) -> float:
        key = (request.symbol, request.strategy_id)
        current_pos = self._positions.get(key)
        current_qty = current_pos.quantity if current_pos else 0

        # If order reduces position, it releases margin rather than requiring additional margin
        if (current_qty > 0 and request.action == OrderAction.SELL) or (
            current_qty < 0 and request.action == OrderAction.BUY
        ):
            if request.quantity <= abs(current_qty):
                return 0.0  # Fully reducing, 0 additional margin

        # Increasing exposure
        if request.product_type == ProductType.CNC:
            return request.quantity * ref_price
        elif request.symbol in self.fixed_margins:
            return self.fixed_margins[request.symbol]
        else:
            return request.quantity * ref_price * self.default_margin_pct
