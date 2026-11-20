"""
Unit tests for PaperBroker and Broker Base Contracts (Step 2D.1).
"""

import pytest
from datetime import datetime
from src.brokers import (
    PaperBroker,
    OrderRequest,
    OrderStatus,
    ProductType,
)
from src.schema.strategy import InstrumentType, OrderAction, OrderType


@pytest.mark.asyncio
async def test_initial_balance_and_ledger():
    broker = PaperBroker(initial_capital=100_000.0)
    balance = await broker.get_balance()

    assert balance.cash_balance == 100_000.0
    assert balance.used_margin == 0.0
    assert balance.available_margin == 100_000.0
    assert balance.realized_pnl == 0.0
    assert balance.unrealized_pnl == 0.0
    assert balance.total_equity == 100_000.0


@pytest.mark.asyncio
async def test_immediate_market_buy_and_position():
    broker = PaperBroker(initial_capital=100_000.0, default_margin_pct=0.20, slippage_pct=0.001)
    broker.on_tick("MCX:ALUMINI", 250.0)

    # Place Market BUY 1000 units (1 MT) at ~250
    order_req = OrderRequest(
        strategy_id="mcx_aluminium_test",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
        instrument_type=InstrumentType.FUTURES,
        product_type=ProductType.NRML,
    )
    resp = await broker.place_order(order_req)

    assert resp.status == OrderStatus.FILLED
    assert resp.filled_quantity == 1000
    # Price with 0.1% slippage = 250 * 1.001 = 250.25
    assert resp.average_price == 250.25

    # Check position
    pos = await broker.get_position("MCX:ALUMINI", "mcx_aluminium_test")
    assert pos is not None
    assert pos.quantity == 1000
    assert pos.average_entry_price == 250.25

    # Check margin
    balance = await broker.get_balance()
    # Required margin = 1000 * 250.25 * 0.20 = 50,050 (or 50,000 on 250 tick)
    assert balance.used_margin >= 50_000.0
    assert balance.available_margin < 50_000.0


@pytest.mark.asyncio
async def test_market_sell_and_realized_pnl():
    broker = PaperBroker(initial_capital=100_000.0, default_margin_pct=0.20, slippage_pct=0.0)
    broker.on_tick("MCX:ALUMINI", 250.0)

    # 1. Buy 1000 @ 250
    await broker.place_order(OrderRequest(
        strategy_id="mcx_aluminium_test",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))

    # 2. Market price rises to 255.0
    broker.on_tick("MCX:ALUMINI", 255.0)
    pos = await broker.get_position("MCX:ALUMINI", "mcx_aluminium_test")
    assert pos.pnl_unrealized == (255.0 - 250.0) * 1000  # +5,000

    # 3. Sell 1000 @ 255.0 to close position
    sell_resp = await broker.place_order(OrderRequest(
        strategy_id="mcx_aluminium_test",
        symbol="MCX:ALUMINI",
        action=OrderAction.SELL,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))
    assert sell_resp.status == OrderStatus.FILLED

    # Position should now be flat
    pos_after = await broker.get_position("MCX:ALUMINI", "mcx_aluminium_test")
    assert pos_after is None  # get_position only returns active non-zero position

    balance = await broker.get_balance()
    assert balance.realized_pnl == 5000.0
    assert balance.used_margin == 0.0
    # Net cash should be initial + 5000 - friction costs
    assert balance.cash_balance > 104_000.0


@pytest.mark.asyncio
async def test_short_selling_and_covering():
    broker = PaperBroker(initial_capital=100_000.0, default_margin_pct=0.20, slippage_pct=0.0)
    broker.on_tick("MCX:ALUMINI", 250.0)

    # 1. Open SHORT position: SELL 1000 @ 250
    await broker.place_order(OrderRequest(
        strategy_id="short_strat",
        symbol="MCX:ALUMINI",
        action=OrderAction.SELL,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))

    pos = await broker.get_position("MCX:ALUMINI", "short_strat")
    assert pos is not None
    assert pos.quantity == -1000
    assert pos.average_entry_price == 250.0

    # 2. Price drops to 246.0 (profitable short)
    broker.on_tick("MCX:ALUMINI", 246.0)
    pos = await broker.get_position("MCX:ALUMINI", "short_strat")
    assert pos.pnl_unrealized == (250.0 - 246.0) * 1000  # +4,000

    # 3. Cover short: BUY 1000 @ 246
    await broker.place_order(OrderRequest(
        strategy_id="short_strat",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))

    balance = await broker.get_balance()
    assert balance.realized_pnl == 4000.0
    assert balance.used_margin == 0.0


@pytest.mark.asyncio
async def test_limit_order_pending_and_tick_fill():
    broker = PaperBroker(initial_capital=100_000.0, slippage_pct=0.0)
    broker.on_tick("MCX:ALUMINI", 252.0)

    # Place BUY LIMIT at 250.0 (below market 252.0)
    resp = await broker.place_order(OrderRequest(
        strategy_id="limit_strat",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.LIMIT,
        price=250.0,
        quantity=1000,
    ))

    # Should be OPEN, not FILLED
    assert resp.status == OrderStatus.OPEN
    open_orders = await broker.get_open_orders("limit_strat")
    assert len(open_orders) == 1

    # Market tick drops to 251.0 (still above limit) -> remains open
    filled = broker.on_tick("MCX:ALUMINI", 251.0)
    assert len(filled) == 0

    # Market tick drops to 249.50 (crosses limit 250.0) -> fills!
    filled = broker.on_tick("MCX:ALUMINI", 249.50)
    assert len(filled) == 1
    assert filled[0].status == OrderStatus.FILLED
    assert filled[0].average_price == 249.50

    open_orders_after = await broker.get_open_orders("limit_strat")
    assert len(open_orders_after) == 0


@pytest.mark.asyncio
async def test_cancel_open_order():
    broker = PaperBroker(initial_capital=100_000.0)
    broker.on_tick("NESTLEIND", 2200.0)

    # Place limit order
    order = await broker.place_order(OrderRequest(
        strategy_id="test",
        symbol="NESTLEIND",
        action=OrderAction.BUY,
        order_type=OrderType.LIMIT,
        price=2100.0,
        quantity=50,
    ))
    assert order.status == OrderStatus.OPEN

    # Cancel it
    success = await broker.cancel_order(order.order_id)
    assert success is True

    # Verify status
    cancelled = await broker.get_order(order.order_id)
    assert cancelled.status == OrderStatus.CANCELLED

    # Open orders list should be empty
    open_orders = await broker.get_open_orders("test")
    assert len(open_orders) == 0


@pytest.mark.asyncio
async def test_insufficient_margin_rejection():
    # Only ₹20,000 capital
    broker = PaperBroker(initial_capital=20_000.0, default_margin_pct=0.20)
    broker.on_tick("MCX:ALUMINIUM", 250.0)

    # Big lot: 5000 units * 250 = ₹12,50,000 turnover -> 20% margin = ₹2,50,000
    resp = await broker.place_order(OrderRequest(
        strategy_id="big_lot_test",
        symbol="MCX:ALUMINIUM",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=5000,
    ))

    assert resp.status == OrderStatus.REJECTED
    assert "Insufficient margin" in resp.message


@pytest.mark.asyncio
async def test_transaction_friction_deduction():
    broker = PaperBroker(initial_capital=100_000.0, slippage_pct=0.001)
    broker.on_tick("MCX:ALUMINI", 250.0)

    # Buy and sell at exactly 250 (flat trade, zero gross PnL)
    await broker.place_order(OrderRequest(
        strategy_id="test",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))
    broker.on_tick("MCX:ALUMINI", 250.0)
    await broker.place_order(OrderRequest(
        strategy_id="test",
        symbol="MCX:ALUMINI",
        action=OrderAction.SELL,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))

    balance = await broker.get_balance()
    # Because of slippage + taxes, cash should strictly be less than 100,000
    assert balance.cash_balance < 100_000.0
    assert broker._total_costs > 0.0


@pytest.mark.asyncio
async def test_candle_bar_matching():
    broker = PaperBroker(initial_capital=100_000.0, slippage_pct=0.0)
    broker.on_tick("MCX:ALUMINI", 250.0)

    # Place BUY LIMIT at 248.0
    await broker.place_order(OrderRequest(
        strategy_id="bar_test",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.LIMIT,
        price=248.0,
        quantity=1000,
    ))

    # Bar 1: High=252, Low=249 -> does NOT cross 248.0
    filled1 = broker.on_bar("MCX:ALUMINI", open_=250.0, high=252.0, low=249.0, close=251.0)
    assert len(filled1) == 0

    # Bar 2: High=251, Low=247 -> LOW dips below 248.0 -> triggers fill!
    filled2 = broker.on_bar("MCX:ALUMINI", open_=251.0, high=251.5, low=247.0, close=248.5)
    assert len(filled2) == 1
    assert filled2[0].status == OrderStatus.FILLED
    assert filled2[0].average_price == 248.0


@pytest.mark.asyncio
async def test_multi_strategy_isolation():
    broker = PaperBroker(initial_capital=200_000.0, slippage_pct=0.0)
    broker.on_tick("MCX:ALUMINI", 250.0)
    broker.on_tick("DIVISLAB", 5000.0)

    # Strategy 1 trades Aluminium
    await broker.place_order(OrderRequest(
        strategy_id="strat_aluminium",
        symbol="MCX:ALUMINI",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=1000,
    ))

    # Strategy 2 trades DivisLab
    await broker.place_order(OrderRequest(
        strategy_id="strat_52_high",
        symbol="DIVISLAB",
        action=OrderAction.BUY,
        order_type=OrderType.MARKET,
        quantity=20,
    ))

    # Verify positions isolation
    strat1_positions = await broker.get_positions(strategy_id="strat_aluminium")
    assert len(strat1_positions) == 1
    assert strat1_positions[0].symbol == "MCX:ALUMINI"

    strat2_positions = await broker.get_positions(strategy_id="strat_52_high")
    assert len(strat2_positions) == 1
    assert strat2_positions[0].symbol == "DIVISLAB"

    # All positions
    all_positions = await broker.get_positions()
    assert len(all_positions) == 2
