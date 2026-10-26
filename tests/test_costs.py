import pytest
from src.schema.strategy import InstrumentType, OrderAction
from src.engine.costs import TransactionCostModel, TradeCost


def test_equity_delivery_costs():
    model = TransactionCostModel(brokerage_per_order=0.0, equity_slippage_pct=0.0005)
    # BUY ₹1,00,000 worth of Equity delivery
    buy_cost = model.calculate(
        action=OrderAction.BUY,
        instrument_type=InstrumentType.EQUITY,
        price=1000.0,
        quantity=100,
        is_intraday=False,
    )
    # STT: 0.1% on buy = 100.0
    assert buy_cost.stt == 100.0
    # Stamp duty: 0.015% on buy = 15.0
    assert buy_cost.stamp_duty == 15.0
    # Exchange charges: 100000 * 0.0000345 = 3.45
    assert buy_cost.exchange_charges == 3.45
    # GST: 18% of 3.45 = 0.62
    assert buy_cost.gst == 0.62
    # Slippage: 0.05% of 100,000 = 50.0
    assert buy_cost.slippage_amount == 50.0


def test_futures_costs_stt_sell_only():
    model = TransactionCostModel(brokerage_per_order=20.0, futures_slippage_pct=0.0)
    # BUY 1 lot Nifty Futures (e.g. price 25,000, lot size 25) -> Turnover = 625,000
    buy_cost = model.calculate(
        action=OrderAction.BUY,
        instrument_type=InstrumentType.FUTURES,
        price=25000.0,
        quantity=25,
    )
    # STT on buy should be 0.0
    assert buy_cost.stt == 0.0
    # Stamp duty on buy: 625,000 * 0.00002 = 12.50
    assert buy_cost.stamp_duty == 12.50

    # SELL Nifty Futures
    sell_cost = model.calculate(
        action=OrderAction.SELL,
        instrument_type=InstrumentType.FUTURES,
        price=25000.0,
        quantity=25,
    )
    # STT on sell: 625,000 * 0.0002 = 125.0
    assert sell_cost.stt == 125.0
    # Stamp duty on sell should be 0.0
    assert sell_cost.stamp_duty == 0.0


def test_options_premium_turnover():
    model = TransactionCostModel(brokerage_per_order=20.0, options_slippage_pct=0.001)
    # SELL 1 lot ATM Call option at ₹150 premium, lot size 25 -> Turnover = 3,750
    cost = model.calculate(
        action=OrderAction.SELL,
        instrument_type=InstrumentType.CE,
        price=150.0,
        quantity=25,
    )
    # STT on sell premium: 3750 * 0.001 = 3.75
    assert cost.stt == 3.75
    # Exchange charges: 3750 * 0.0005 = 1.88
    assert cost.exchange_charges == 1.88
    # Brokerage = 20.0
    assert cost.brokerage == 20.0
    # Total should sum all non-zero components
    assert cost.total > 25.0
