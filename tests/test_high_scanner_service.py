"""Unit and integration tests for HighScannerService (52-Week High Strategy Facade)."""

from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.scanner.high_service import HighScannerService
from src.scanner.models import (
    BreakoutSignal,
    BreakoutStage,
    ConsolidationBaseMetrics,
    ExhaustionMetrics,
    FundamentalAudit,
    HighStockStatusBadge,
    SellReason,
)
from tests.test_52_high_scanner import generate_breakout_candles, MockCacheManager, MockScreenerClient, MockInsiderFeed


@pytest.fixture
def test_high_service(tmp_path):
    """Create a fully configured HighScannerService with isolated temp paths."""
    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    df_trent = generate_breakout_candles(n_bars=260, base_price=1000.0, volume_multiplier=3.2)
    mock_cache = MockCacheManager({"TRENT": df_trent})
    mock_screener = MockScreenerClient(pass_growth=True)
    mock_insider = MockInsiderFeed()

    svc = HighScannerService(
        cache_dir=str(cache_dir),
        data_dir=str(data_dir),
        cache_manager=mock_cache,
        screener_client=mock_screener,
        insider_feed=mock_insider,
    )
    return svc


def test_daily_briefing_end_to_end(test_high_service):
    """Verify get_daily_briefing executes all 4 steps cleanly."""
    dashboard = test_high_service.get_daily_briefing(
        candidate_symbols=["TRENT"],
        as_of_date="2026-11-10",
        skip_fundamental_audit=True,
        current_prices_and_emas={"TRENT": (1020.0, 960.0)},
    )

    assert dashboard.as_of_date == "2026-11-10"
    assert len(dashboard.new_radar_signals) == 1
    assert dashboard.new_radar_signals[0].symbol == "TRENT"
    assert len(dashboard.summary_notes) > 0

    md = test_high_service.format_daily_briefing_markdown(dashboard)
    assert "# 🚀 QuantCopilot: 52-Week High Breakout Briefing" in md
    assert "TRENT" in md


def test_scan_radar_candidates(test_high_service):
    """Verify radar scan returns signals and formatted markdown."""
    signals, md = test_high_service.scan_radar_candidates(
        candidate_symbols=["TRENT"],
        as_of_date="2026-11-10",
    )
    assert len(signals) == 1
    assert signals[0].symbol == "TRENT"
    assert "52-Week High Breakout Radar" in md


def test_watchlist_and_portfolio_summaries(test_high_service):
    """Verify empty and populated watchlist & portfolio summary queries."""
    # Initially empty
    w_list, w_md = test_high_service.get_watchlist_summary(as_of_date="2026-11-10")
    assert len(w_list) == 0
    assert "empty" in w_md

    p_list, p_md = test_high_service.get_portfolio_summary(as_of_date="2026-11-10")
    assert len(p_list) == 0
    assert "No active holdings" in p_md

    # Add to watchlist
    w_stock = test_high_service.add_to_watchlist("TRENT", user_notes="Tight VCP base", as_of_date="2026-11-10")
    assert w_stock.symbol == "TRENT"

    w_list2, w_md2 = test_high_service.get_watchlist_summary(as_of_date="2026-11-10")
    assert len(w_list2) == 1
    assert "TRENT" in w_md2


def test_buy_and_sell_lifecycle(test_high_service):
    """Verify end-to-end buy, partial sell at T1, and full exit archiving to ledger."""
    bought = test_high_service.record_buy(
        symbol="TRENT",
        entry_price=1000.0,
        quantity=100,
        entry_date="2026-11-01",
        notes="Stage 2 buy",
    )
    assert bought.symbol == "TRENT"
    assert bought.remaining_quantity == 100

    # Partial sell 50 shares
    p_stock, ledger = test_high_service.record_sell(
        symbol="TRENT",
        sell_price=1150.0,
        quantity=50,
        reason=SellReason.TARGET_1,
        sell_date="2026-11-05",
    )
    assert p_stock.remaining_quantity == 50
    assert ledger is None

    # Full exit remaining 50 shares
    p_stock2, ledger2 = test_high_service.record_sell(
        symbol="TRENT",
        sell_price=1300.0,
        quantity=50,
        reason=SellReason.TARGET_2,
        sell_date="2026-11-10",
    )
    assert p_stock2.remaining_quantity == 0
    assert ledger2 is not None
    assert ledger2.symbol == "TRENT"
    assert ledger2.total_quantity == 100
    assert ledger2.net_realized_pnl_inr == 22_500.0


def test_audit_single_symbol(test_high_service):
    """Verify audit_single_symbol packages technical, base, and fundamental data."""
    audit_data = test_high_service.audit_single_symbol("TRENT")
    assert audit_data["symbol"] == "TRENT"
    assert "technical_levels" in audit_data
    assert "base_metrics" in audit_data
    assert "fundamental_audit" in audit_data

