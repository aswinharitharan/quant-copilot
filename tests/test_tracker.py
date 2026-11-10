"""Unit and lifecycle tests for PortfolioTracker (Phase C)."""

import json
from pathlib import Path
import pytest

from src.scanner.models import (
    CapitulationSignal,
    FundamentalAudit,
    InsiderTradeRecord,
    SellReason,
    SignalStage,
    StockStatusBadge,
)
from src.scanner.tracker import PortfolioTracker


@pytest.fixture
def temp_tracker(tmp_path: Path) -> PortfolioTracker:
    """Fixture providing a PortfolioTracker rooted in a temporary directory."""
    return PortfolioTracker(data_dir=str(tmp_path / "data"))


def sample_signal(symbol: str = "NESTLEIND") -> CapitulationSignal:
    return CapitulationSignal(
        symbol=symbol,
        capitulation_date="2026-11-08",
        low_price=2100.0,
        high_price=2180.0,
        close_price=2140.0,
        today_volume=1_500_000,
        avg_volume_20d=350_000,
        volume_ratio=4.28,
        support_sl=2100.0,
        target_1_20ema=2250.0,
        target_2_50ema=2380.0,
        audit=FundamentalAudit(
            symbol=symbol,
            audit_date="2026-11-08",
            market_cap_cr=200000.0,
            current_price=2140.0,
            pe_ratio=65.0,
            roce_pct=115.0,
            debt_to_equity=0.10,
            interest_coverage=18.0,
            cfo_last_yr_cr=4500.0,
            promoter_pledge_pct=0.0,
            passed_audit=True,
        ),
        insider_activity=InsiderTradeRecord(
            symbol=symbol,
            filing_date="2026-11-07",
            acquirer_name="Nestle S.A.",
            category="Promoter",
            acquisition_mode="Market Purchase",
            quantity=50_000,
            value_inr=107_000_000.0,
            percent_equity=0.05,
            is_material_promoter_buy=True,
        ),
        stage=SignalStage.RADAR,
    )


# -------------------------------------------------------------------------
# TESTS
# -------------------------------------------------------------------------

def test_watchlist_add_and_retrieve(temp_tracker: PortfolioTracker):
    sig = sample_signal("NESTLEIND")
    item = temp_tracker.add_to_watchlist(sig, user_notes="Testing support thesis")

    assert item.symbol == "NESTLEIND"
    assert item.capitulation_low == 2100.0
    assert item.target_1_20ema == 2250.0
    assert len(item.history_notes) >= 1
    assert "Testing support thesis" in item.history_notes[0]

    # Verify loaded from disk
    loaded = temp_tracker.get_watchlist()
    assert len(loaded) == 1
    assert loaded[0].symbol == "NESTLEIND"


def test_watchlist_cascading_low_reset(temp_tracker: PortfolioTracker):
    sig = sample_signal("TATACONSUM")
    temp_tracker.add_to_watchlist(sig, user_notes="Initial capitulation")

    # Day 2 drops to 900 on 4.5x volume (cascading low)
    updated = temp_tracker.handle_cascading_low(
        symbol="TATACONSUM",
        new_low=2050.0,
        new_high=2120.0,
        new_vol_ratio=4.5,
        new_date="2026-11-09",
        new_target_1=2220.0,
        new_target_2=2350.0,
    )

    assert updated is not None
    assert updated.capitulation_low == 2050.0
    assert updated.capitulation_date == "2026-11-09"
    assert len(updated.history_notes) == 2
    assert "Cascading Capitulation on 2026-11-09" in updated.history_notes[1]


def test_record_buy_moves_from_watchlist_to_portfolio(temp_tracker: PortfolioTracker):
    sig = sample_signal("NESTLEIND")
    temp_tracker.add_to_watchlist(sig, user_notes="Waiting for Stage 2")

    # User buys 100 shares @ 2160
    pos = temp_tracker.record_buy(
        symbol="NESTLEIND",
        entry_price=2160.0,
        quantity=100,
        entry_date="2026-11-10",
        notes="Reclaimed 5 EMA trigger",
    )

    # Watchlist should now be empty
    assert len(temp_tracker.get_watchlist()) == 0

    # Portfolio should have 1 item
    portfolio = temp_tracker.get_portfolio()
    assert len(portfolio) == 1
    assert portfolio[0].symbol == "NESTLEIND"
    assert portfolio[0].entry_price == 2160.0
    assert portfolio[0].total_quantity_bought == 100
    assert portfolio[0].remaining_quantity == 100
    assert portfolio[0].capitulation_low == 2100.0  # Inherited from Watchlist!
    assert portfolio[0].target_1_20ema == 2250.0
    assert portfolio[0].target_2_50ema == 2380.0
    assert len(portfolio[0].history_notes) >= 2


def test_daily_sentinel_badges(temp_tracker: PortfolioTracker):
    temp_tracker.record_buy(
        symbol="STOCK_A",
        entry_price=100.0,
        quantity=100,
        capitulation_low=95.0,
        target_1_20ema=110.0,
        target_2_50ema=120.0,
    )

    # 1. Price is healthy (> 3% above SL) -> SAFE
    evaluated = temp_tracker.evaluate_portfolio_health({"STOCK_A": 102.0})
    assert evaluated[0].status_badge == StockStatusBadge.SAFE
    assert evaluated[0].dist_from_sl_pct > 3.0

    # 2. Price tests support (within 1.5% of 95.0, e.g. 96.0) -> RADAR_ALERT
    evaluated = temp_tracker.evaluate_portfolio_health({"STOCK_A": 96.0})
    assert evaluated[0].status_badge == StockStatusBadge.RADAR_ALERT

    # 3. Price breaches soft stop (< 95.0, e.g. 94.0) -> DECISION_REQD
    evaluated = temp_tracker.evaluate_portfolio_health({"STOCK_A": 94.0})
    assert evaluated[0].status_badge == StockStatusBadge.DECISION_REQD

    # 4. Price rebounds and hits Target 1 (>= 110.0, e.g. 112.0) -> TARGET_1_HIT
    evaluated = temp_tracker.evaluate_portfolio_health({"STOCK_A": 112.0})
    assert evaluated[0].status_badge == StockStatusBadge.TARGET_1_HIT

    # 5. Price rallies to Target 2 (>= 120.0, e.g. 125.0) -> TARGET_2_HIT
    evaluated = temp_tracker.evaluate_portfolio_health({"STOCK_A": 125.0})
    assert evaluated[0].status_badge == StockStatusBadge.TARGET_2_HIT


def test_partial_scaling_and_full_exit_archiving(temp_tracker: PortfolioTracker):
    temp_tracker.record_buy(
        symbol="INFY",
        entry_price=1500.0,
        quantity=100,
        entry_date="2026-11-01",
        capitulation_low=1450.0,
        target_1_20ema=1600.0,
        target_2_50ema=1700.0,
    )

    # Tranche 1: Book 50% at Target 1 (1600)
    stock, archived = temp_tracker.record_partial_sell(
        symbol="INFY",
        sell_price=1600.0,
        quantity=50,
        reason=SellReason.TARGET_1,
        sell_date="2026-11-08",
        notes="Booked 50% at 20 EMA",
    )

    assert stock.remaining_quantity == 50
    assert archived is None  # Position still open
    assert len(stock.partial_sells) == 1
    assert stock.partial_sells[0].realized_pnl_inr == 5000.0  # (1600 - 1500) * 50
    assert len(temp_tracker.get_portfolio()) == 1
    assert len(temp_tracker.get_trade_ledger()) == 0

    # Tranche 2: Book remaining 50% at Target 2 (1700)
    stock_final, archived_ledger = temp_tracker.record_partial_sell(
        symbol="INFY",
        sell_price=1700.0,
        quantity=50,
        reason=SellReason.TARGET_2,
        sell_date="2026-11-15",
        notes="Booked remaining 50% at 50 EMA",
    )

    assert stock_final.remaining_quantity == 0
    assert archived_ledger is not None

    # Portfolio should now be empty
    assert len(temp_tracker.get_portfolio()) == 0

    # Ledger should contain the closed trade
    ledger = temp_tracker.get_trade_ledger()
    assert len(ledger) == 1
    closed = ledger[0]
    assert closed.symbol == "INFY"
    assert closed.total_quantity == 100
    assert closed.total_invested_inr == 150_000.0  # 1500 * 100
    assert closed.total_proceeds_inr == 165_000.0  # (1600 * 50) + (1700 * 50) = 80000 + 85000
    assert closed.net_realized_pnl_inr == 15_000.0
    assert closed.net_return_pct == 10.0
    assert closed.holding_duration_days == 14
    assert len(closed.sells) == 2
    assert len(closed.history_notes) >= 3

