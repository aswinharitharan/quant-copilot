import pytest
from datetime import datetime
import pandas as pd
from src.schema.strategy import InstrumentType, OrderAction
from src.schema.backtest_models import Trade
from src.engine.metrics import MetricsCalculator


def test_metrics_empty():
    calc = MetricsCalculator()
    equity_curve = pd.Series([100000.0], index=pd.date_range("2024-01-01", periods=1))
    metrics = calc.calculate(equity_curve, [], 100000.0)
    assert metrics["total_trades"] == 0
    assert metrics["total_return_pct"] == 0.0
    assert metrics["max_drawdown_pct"] == 0.0


def test_metrics_known_trades():
    calc = MetricsCalculator(risk_free_rate=0.0)
    dates = pd.date_range("2024-01-01", periods=5, freq="1D")
    equity_curve = pd.Series([100000.0, 105000.0, 102000.0, 110000.0, 115000.0], index=dates)

    t1 = Trade(
        trade_id="t1",
        set_id=1,
        leg_id="l1",
        instrument_type=InstrumentType.EQUITY,
        action=OrderAction.BUY,
        entry_time=datetime(2024, 1, 1),
        entry_price=100.0,
        quantity=10,
        exit_time=datetime(2024, 1, 2),
        exit_price=105.0,
        pnl_net=5000.0,
    )
    t2 = Trade(
        trade_id="t2",
        set_id=1,
        leg_id="l1",
        instrument_type=InstrumentType.EQUITY,
        action=OrderAction.BUY,
        entry_time=datetime(2024, 1, 2),
        entry_price=105.0,
        quantity=10,
        exit_time=datetime(2024, 1, 3),
        exit_price=102.0,
        pnl_net=-3000.0,
    )
    t3 = Trade(
        trade_id="t3",
        set_id=1,
        leg_id="l1",
        instrument_type=InstrumentType.EQUITY,
        action=OrderAction.BUY,
        entry_time=datetime(2024, 1, 3),
        entry_price=102.0,
        quantity=10,
        exit_time=datetime(2024, 1, 5),
        exit_price=115.0,
        pnl_net=13000.0,
    )

    metrics = calc.calculate(equity_curve, [t1, t2, t3], 100000.0)

    assert metrics["total_return_pct"] == 15.0  # (115,000 - 100,000) / 100,000 * 100
    assert metrics["total_trades"] == 3
    assert metrics["winning_trades"] == 2
    assert metrics["losing_trades"] == 1
    assert metrics["win_rate_pct"] == 66.67
    assert metrics["profit_factor"] == round((5000.0 + 13000.0) / 3000.0, 2)  # 18000 / 3000 = 6.0
    # Peak is 105k, trough is 102k -> DD = (105k - 102k) / 105k = 2.857%
    assert metrics["max_drawdown_pct"] == 2.86
