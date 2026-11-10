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
    # SEBI: 100,000 * 0.000001 = 0.10
    assert buy_cost.sebi_charges == 0.10
    # Slippage: 0.05% of 100,000 = 50.0
    assert buy_cost.slippage_amount == 50.0
    # GST: 18% of (brokerage + exchange + sebi + slippage) = 0.18 * (3.45 + 0.10 + 50.0) = 9.64
    assert buy_cost.gst == 9.64


def test_futures_costs_updated_rules():
    # Test default updated rules:
    # 1. Slippage = ₹20 buy, ₹20 sell
    # 2. STT = 0.05% on Sell
    # 3. Exchange = 0.00183% on turnover
    # 4. Stamp duty = 0.002% on buy
    # 5. GST = 18% on (Slippage + SEBI + Exchange)
    # 6. SEBI = ₹10/crore (0.0001%)
    model = TransactionCostModel(brokerage_per_order=0.0)
    
    # BUY 1 lot (turnover = ₹6,00,000)
    buy_cost = model.calculate(
        action=OrderAction.BUY,
        instrument_type=InstrumentType.FUTURES,
        price=6000.0,
        quantity=100,
    )
    assert buy_cost.stt == 0.0
    assert buy_cost.slippage_amount == 20.0  # ₹20 on buy
    assert buy_cost.stamp_duty == 12.0  # 600,000 * 0.00002 = 12.0
    assert buy_cost.exchange_charges == 10.98  # 600,000 * 0.0000183 = 10.98
    assert buy_cost.sebi_charges == 0.60  # 600,000 * 0.000001 = 0.60
    # GST: 18% of (20.0 + 10.98 + 0.60) = 18% of 31.58 = 5.68
    assert buy_cost.gst == 5.68

    # SELL 1 lot (turnover = ₹6,00,000)
    sell_cost = model.calculate(
        action=OrderAction.SELL,
        instrument_type=InstrumentType.FUTURES,
        price=6000.0,
        quantity=100,
    )
    # STT: 0.05% on sell = 600,000 * 0.0005 = 300.0
    assert sell_cost.stt == 300.0
    assert sell_cost.slippage_amount == 20.0  # ₹20 on sell
    assert sell_cost.stamp_duty == 0.0  # Stamp duty is buy only
    assert sell_cost.exchange_charges == 10.98
    assert sell_cost.sebi_charges == 0.60
    assert sell_cost.gst == 5.68


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
    assert cost.total > 25.0
