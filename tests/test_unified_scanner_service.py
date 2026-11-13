"""Tests for UnifiedScannerService (orchestrating both 52W High and 52W Low strategies)."""

from unittest.mock import MagicMock
import pytest

from src.scanner.models import (
    BreakoutSignal,
    CapitulationSignal,
    ConsolidationBaseMetrics,
    DailyDashboard52,
    DailyDashboard52High,
    ExhaustionMetrics,
    FundamentalAudit,
    HighPortfolioStock,
    HighStockStatusBadge,
    HighWatchlistStock,
    InsiderTradeRecord,
    PortfolioStock,
    StockStatusBadge,
    WatchlistStock,
)
from src.scanner.unified_service import UnifiedScannerService


@pytest.fixture
def sample_high_dashboard():
    return DailyDashboard52High(
        as_of_date="2026-11-13",
        summary_notes=["Monitored 1 active 52W High holding."],
        watchlist_buy_triggers=[
            HighWatchlistStock(
                symbol="TRENT",
                added_date="2026-11-10",
                breakout_date="2026-11-10",
                breakout_price=7150.0,
                pivot_high=7200.0,
                initial_sl=6768.0,
                trailing_20ema=6900.0,
                target_1_15pct=8280.0,
                target_2_30pct=9360.0,
                is_buy_triggered=True,
                trigger_price=7250.0,
            )
        ],
        new_radar_signals=[
            BreakoutSignal(
                symbol="BEL",
                breakout_date="2026-11-13",
                breakout_price=340.0,
                high_52w=340.0,
                today_high=342.0,
                today_low=335.0,
                today_volume=15000000,
                avg_volume_20d=7000000,
                volume_ratio=2.14,
                initial_sl=319.60,
                trailing_20ema=325.0,
                target_1_15pct=391.0,
                target_2_30pct=442.0,
                base_metrics=ConsolidationBaseMetrics(
                    base_duration_days=35,
                    base_depth_pct=11.5,
                    atr_contraction_ratio=0.72,
                    above_150_sma=True,
                    above_200_sma=True,
                    rising_200_sma=True,
                    passed_base_check=True,
                ),
                exhaustion=ExhaustionMetrics(),
                audit=FundamentalAudit(symbol="BEL", audit_date="2026-11-13", passed_audit=True),
            )
        ],
        active_portfolio_status=[
            HighPortfolioStock(
                symbol="HAL",
                entry_date="2026-11-01",
                entry_price=4500.0,
                total_quantity_bought=20,
                remaining_quantity=20,
                current_price=4900.0,
                initial_sl=4230.0,
                highest_high_since_entry=4920.0,
                trailing_sl=4650.0,
                unrealized_pnl_pct=8.89,
                status_badge=HighStockStatusBadge.SAFE,
                target_1_15pct=5175.0,
                target_2_30pct=5850.0,
            )
        ],
        material_insider_trades=[
            InsiderTradeRecord(
                symbol="TRENT",
                acquirer_name="Tata Sons Pvt Ltd",
                category="Promoter",
                acquisition_mode="Market Purchase",
                quantity=10000,
                value_inr=72000000.0,
                filing_date="2026-11-12",
            )
        ],
    )


@pytest.fixture
def sample_low_dashboard():
    return DailyDashboard52(
        as_of_date="2026-11-13",
        summary_notes=["Monitored 1 active 52W Low holding."],
        watchlist_buy_triggers=[
            WatchlistStock(
                symbol="NESTLEIND",
                added_date="2026-11-05",
                capitulation_date="2026-11-05",
                capitulation_low=2120.0,
                capitulation_high=2180.0,
                target_1_20ema=2280.0,
                target_2_50ema=2380.0,
                is_buy_triggered=True,
                trigger_price=2160.0,
            )
        ],
        new_radar_signals=[
            CapitulationSignal(
                symbol="TATACONSUM",
                capitulation_date="2026-11-13",
                close_price=890.0,
                low_price=885.0,
                high_price=905.0,
                today_volume=12000000,
                avg_volume_20d=3500000,
                volume_ratio=3.43,
                support_sl=858.45,
                target_1_20ema=940.0,
                target_2_50ema=990.0,
                audit=FundamentalAudit(symbol="TATACONSUM", audit_date="2026-11-13", passed_audit=True),
            )
        ],
        active_portfolio_status=[
            PortfolioStock(
                symbol="THERMAX",
                entry_date="2026-11-07",
                entry_price=2750.0,
                total_quantity_bought=30,
                remaining_quantity=30,
                current_price=2840.0,
                capitulation_low=2666.60,
                target_1_20ema=3100.0,
                target_2_50ema=3400.0,
                unrealized_pnl_pct=3.27,
                dist_from_sl_pct=6.5,
                status_badge=StockStatusBadge.SAFE,
            )
        ],
        material_insider_trades=[
            InsiderTradeRecord(
                symbol="NESTLEIND",
                acquirer_name="Nestle S.A.",
                category="Promoter",
                acquisition_mode="Market Purchase",
                quantity=50000,
                value_inr=108000000.0,
                filing_date="2026-11-11",
            )
        ],
    )


def test_unified_briefing_both_strategies(sample_low_dashboard, sample_high_dashboard):
    mock_low = MagicMock()
    mock_low.get_daily_briefing.return_value = sample_low_dashboard

    mock_high = MagicMock()
    mock_high.get_daily_briefing.return_value = sample_high_dashboard

    svc = UnifiedScannerService(low_service=mock_low, high_service=mock_high)
    briefing = svc.get_unified_daily_briefing(as_of_date="2026-11-13", strategy="both")

    assert briefing["as_of_date"] == "2026-11-13"
    assert briefing["low_dashboard"] == sample_low_dashboard
    assert briefing["high_dashboard"] == sample_high_dashboard

    mock_low.get_daily_briefing.assert_called_once()
    mock_high.get_daily_briefing.assert_called_once()

    md = svc.format_unified_briefing_markdown(briefing)
    assert "# 📊 QuantCopilot: Unified 52-Week Briefing — 2026-11-13" in md
    # High strategy section checks
    assert "## 🚀 A. 52-Week HIGH — Breakout Strategy" in md
    assert "TRENT" in md
    assert "BEL" in md
    assert "HAL" in md
    # Low strategy section checks
    assert "## 📉 B. 52-Week LOW — Capitulation Strategy" in md
    assert "NESTLEIND" in md
    assert "TATACONSUM" in md
    assert "THERMAX" in md
    # Insider section checks
    assert "## 💼 C. Material Promoter Buying" in md
    assert "Tata Sons Pvt Ltd" in md
    assert "Nestle S.A." in md


def test_unified_briefing_strategy_high_only(sample_high_dashboard):
    mock_low = MagicMock()
    mock_high = MagicMock()
    mock_high.get_daily_briefing.return_value = sample_high_dashboard

    svc = UnifiedScannerService(low_service=mock_low, high_service=mock_high)
    briefing = svc.get_unified_daily_briefing(as_of_date="2026-11-13", strategy="high")

    assert briefing["low_dashboard"] is None
    assert briefing["high_dashboard"] == sample_high_dashboard
    mock_low.get_daily_briefing.assert_not_called()
    mock_high.get_daily_briefing.assert_called_once()

    md = svc.format_unified_briefing_markdown(briefing)
    assert "52-Week HIGH" in md
    assert "52-Week LOW" not in md


def test_unified_briefing_strategy_low_only(sample_low_dashboard):
    mock_low = MagicMock()
    mock_low.get_daily_briefing.return_value = sample_low_dashboard
    mock_high = MagicMock()

    svc = UnifiedScannerService(low_service=mock_low, high_service=mock_high)
    briefing = svc.get_unified_daily_briefing(as_of_date="2026-11-13", strategy="low")

    assert briefing["high_dashboard"] is None
    assert briefing["low_dashboard"] == sample_low_dashboard
    mock_high.get_daily_briefing.assert_not_called()
    mock_low.get_daily_briefing.assert_called_once()

    md = svc.format_unified_briefing_markdown(briefing)
    assert "52-Week LOW" in md
    assert "52-Week HIGH" not in md


def test_unified_briefing_graceful_error_handling(sample_low_dashboard):
    mock_low = MagicMock()
    mock_low.get_daily_briefing.return_value = sample_low_dashboard
    mock_high = MagicMock()
    mock_high.get_daily_briefing.side_effect = RuntimeError("NSE High API Timeout")

    svc = UnifiedScannerService(low_service=mock_low, high_service=mock_high)
    briefing = svc.get_unified_daily_briefing(as_of_date="2026-11-13", strategy="both")

    assert briefing["high_dashboard"] is None
    assert briefing["high_error"] == "NSE High API Timeout"
    assert briefing["low_dashboard"] == sample_low_dashboard

    md = svc.format_unified_briefing_markdown(briefing)
    assert "⚠️ Error: NSE High API Timeout" in md
    assert "## 📉 B. 52-Week LOW — Capitulation Strategy" in md
