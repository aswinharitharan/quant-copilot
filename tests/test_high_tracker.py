"""Unit tests for HighPortfolioTracker (52-Week High 3-Tier Storage & Trailing Stop)."""

import json
from pathlib import Path
import pytest

from src.scanner.high_tracker import HighPortfolioTracker
from src.scanner.models import (
    BreakoutSignal,
    BreakoutStage,
    ConsolidationBaseMetrics,
    ExhaustionMetrics,
    FundamentalAudit,
    HighStockStatusBadge,
    SellReason,
)


@pytest.fixture
def temp_tracker(tmp_path):
    """Return a HighPortfolioTracker instance backed by a temporary directory."""
    return HighPortfolioTracker(data_dir=str(tmp_path))


def create_dummy_signal(symbol: str = "TRENT") -> BreakoutSignal:
    return BreakoutSignal(
        symbol=symbol,
        breakout_date="2026-11-05",
        breakout_price=1000.0,
        high_52w=1005.0,
        today_high=1010.0,
        today_low=980.0,
        today_volume=350000,
        avg_volume_20d=100000.0,
        volume_ratio=3.5,
        initial_sl=940.0,
        trailing_20ema=950.0,
        target_1_15pct=1150.0,
        target_2_30pct=1300.0,
        base_metrics=ConsolidationBaseMetrics(
            base_duration_days=45,
            base_depth_pct=12.0,
            atr_contraction_ratio=0.65,
            above_150_sma=True,
            above_200_sma=True,
            rising_200_sma=True,
            passed_base_check=True,
        ),
        exhaustion=ExhaustionMetrics(),
        audit=FundamentalAudit(symbol=symbol, audit_date="2026-11-05", passed_audit=True),
        stage=BreakoutStage.RADAR,
    )


def test_watchlist_lifecycle(temp_tracker):
    """Test adding and removing from 52W High Watchlist."""
    sig = create_dummy_signal("HAL")
    w = temp_tracker.add_to_watchlist(sig, user_notes="Base breakout")

    assert w.symbol == "HAL"
    assert w.pivot_high == 1010.0
    assert w.target_1_15pct == 1150.0

    # Read back from disk
    items = temp_tracker.get_watchlist()
    assert len(items) == 1
    assert items[0].symbol == "HAL"

    # Remove
    assert temp_tracker.remove_from_watchlist("HAL") is True
    assert len(temp_tracker.get_watchlist()) == 0


def test_record_buy_from_watchlist(temp_tracker):
    """Test buying a stock currently on the watchlist."""
    sig = create_dummy_signal("BEL")
    temp_tracker.add_to_watchlist(sig)

    # Buy executes
    p = temp_tracker.record_buy(symbol="BEL", entry_price=1015.0, quantity=100, entry_date="2026-11-06")

    assert p.symbol == "BEL"
    assert p.entry_price == 1015.0
    assert p.remaining_quantity == 100
    assert p.trailing_sl >= 940.0

    # Watchlist should now be empty (auto-removed on buy)
    assert len(temp_tracker.get_watchlist()) == 0
    assert len(temp_tracker.get_portfolio()) == 1


def test_trailing_sl_ratchet_and_status_badges(temp_tracker):
    """Test trailing SL ratchets UP and never down, and sets correct badges."""
    temp_tracker.record_buy(
        symbol="TRENT",
        entry_price=1000.0,
        quantity=50,
        initial_sl=940.0,
        trailing_20ema=950.0,
        target_1_15pct=1150.0,
        target_2_30pct=1300.0,
    )

    # Day 1: Price climbs to 1080, 20 EMA rises to 980
    temp_tracker.update_portfolio_prices({"TRENT": (1080.0, 980.0)}, as_of_date="2026-11-07")
    p = temp_tracker.get_portfolio()[0]
    assert p.trailing_sl == 980.0
    assert p.status_badge == HighStockStatusBadge.SAFE

    # Day 2: Market dips slightly, 20 EMA drops to 975 -> Trailing SL must NOT drop!
    temp_tracker.update_portfolio_prices({"TRENT": (1060.0, 975.0)}, as_of_date="2026-11-08")
    p = temp_tracker.get_portfolio()[0]
    assert p.trailing_sl == 980.0  # Kept prior high watermark

    # Day 3: Price hits Target 1 (+15% = 1150)
    temp_tracker.update_portfolio_prices({"TRENT": (1155.0, 1020.0)}, as_of_date="2026-11-09")
    p = temp_tracker.get_portfolio()[0]
    assert p.status_badge == HighStockStatusBadge.TARGET_1_HIT
    assert p.trailing_sl >= 1020.0

    # Day 4: Close below trailing SL -> 1st close triggers RADAR_ALERT
    temp_tracker.update_portfolio_prices({"TRENT": (1010.0, 1020.0)}, as_of_date="2026-11-10")
    p = temp_tracker.get_portfolio()[0]
    assert p.status_badge == HighStockStatusBadge.RADAR_ALERT

    # Day 5: 2nd consecutive close below trailing SL -> DECISION_REQD
    temp_tracker.update_portfolio_prices({"TRENT": (1005.0, 1020.0)}, as_of_date="2026-11-11")
    p = temp_tracker.get_portfolio()[0]
    assert p.status_badge == HighStockStatusBadge.DECISION_REQD


def test_partial_sell_and_full_exit_ledger_archive(temp_tracker):
    """Test scaling out 50% at T1, then full exit archiving into Tier 3 Ledger."""
    temp_tracker.record_buy(
        symbol="DIXON",
        entry_price=1000.0,
        quantity=100,
        entry_date="2026-10-01",
    )

    # 1. Partial sell: 50 shares @ 1150 (T1 hit)
    stock, ledger = temp_tracker.record_sell(
        symbol="DIXON",
        sell_price=1150.0,
        quantity=50,
        reason=SellReason.TARGET_1,
        sell_date="2026-10-15",
    )
    assert stock.remaining_quantity == 50
    assert ledger is None  # Not completely exited yet
    assert len(temp_tracker.get_portfolio()) == 1
    assert len(temp_tracker.get_closed_trades()) == 0

    # 2. Final sell: remaining 50 shares @ 1300 (T2 hit)
    stock, ledger = temp_tracker.record_sell(
        symbol="DIXON",
        sell_price=1300.0,
        quantity=50,
        reason=SellReason.TARGET_2,
        sell_date="2026-11-01",
    )
    assert stock.remaining_quantity == 0
    assert ledger is not None
    assert ledger.symbol == "DIXON"
    assert ledger.total_quantity == 100
    assert ledger.total_invested_inr == 100_000.0
    # Proceeds: (50 * 1150) + (50 * 1300) = 57,500 + 65,000 = 122,500
    assert ledger.total_proceeds_inr == 122_500.0
    assert ledger.net_realized_pnl_inr == 22_500.0
    assert ledger.net_return_pct == 22.5

    # Portfolio should now be empty; ledger should have 1 record
    assert len(temp_tracker.get_portfolio()) == 0
    assert len(temp_tracker.get_closed_trades()) == 1

