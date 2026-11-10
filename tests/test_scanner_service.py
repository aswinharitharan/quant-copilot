"""Unit and integration tests for ScannerService (Phase D)."""

from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import pytest

from src.scanner.models import (
    CapitulationSignal,
    DailyDashboard52,
    FundamentalAudit,
    InsiderTradeRecord,
    SellReason,
    SignalStage,
    StockStatusBadge,
    WatchlistStock,
)
from src.scanner.service import ScannerService


class MockScreener:
    def audit_company(self, symbol: str) -> FundamentalAudit:
        return FundamentalAudit(
            symbol=symbol,
            audit_date="2026-11-10",
            market_cap_cr=50000.0,
            current_price=1000.0,
            pe_ratio=25.0,
            roce_pct=22.0,
            debt_to_equity=0.20,
            interest_coverage=10.0,
            cfo_last_yr_cr=2500.0,
            promoter_pledge_pct=0.0,
            passed_audit=True,
        )


class MockInsider:
    def fetch_nse_pit(self) -> List[InsiderTradeRecord]:
        return [
            InsiderTradeRecord(
                symbol="NESTLEIND",
                filing_date="2026-11-09",
                acquirer_name="Nestle S.A.",
                category="Promoter",
                acquisition_mode="Market Purchase",
                quantity=20000,
                value_inr=42000000.0,
                percent_equity=0.02,
                is_material_promoter_buy=True,
            )
        ]

    def get_symbol_insider_activity(self, symbol: str):
        if symbol == "NESTLEIND":
            return self.fetch_nse_pit()[0]
        return None


@pytest.fixture
def temp_service(tmp_path: Path) -> ScannerService:
    cache_d = tmp_path / "cache"
    data_d = tmp_path / "data"
    cache_d.mkdir()
    data_d.mkdir()

    return ScannerService(
        cache_dir=str(cache_d),
        data_dir=str(data_d),
        screener_client=MockScreener(),
        insider_feed=MockInsider(),
    )


# -------------------------------------------------------------------------
# TESTS
# -------------------------------------------------------------------------

def test_portfolio_summary_fast(temp_service: ScannerService):
    # Initially empty
    stocks, summary = temp_service.get_portfolio_summary()
    assert len(stocks) == 0
    assert "0 open positions" in summary

    # Buy a stock
    temp_service.record_buy(
        symbol="NESTLEIND",
        entry_price=2150.0,
        quantity=100,
        notes="5 EMA test",
    )

    stocks, summary = temp_service.get_portfolio_summary(current_prices={"NESTLEIND": 2200.0})
    assert len(stocks) == 1
    assert stocks[0].symbol == "NESTLEIND"
    assert "🟢 SAFE" in summary
    assert "NESTLEIND" in summary


def test_watchlist_summary_fast(temp_service: ScannerService):
    # Initially empty
    items, summary = temp_service.get_watchlist_summary()
    assert len(items) == 0
    assert "0 stocks" in summary

    # Add item to watchlist via tracker
    sig = CapitulationSignal(
        symbol="TATACONSUM",
        capitulation_date="2026-11-08",
        low_price=900.0,
        high_price=940.0,
        close_price=920.0,
        today_volume=1000000,
        avg_volume_20d=250000,
        volume_ratio=4.0,
        support_sl=900.0,
        target_1_20ema=960.0,
        target_2_50ema=1010.0,
        audit=MockScreener().audit_company("TATACONSUM"),
        stage=SignalStage.RADAR,
    )
    temp_service.tracker.add_to_watchlist(sig, user_notes="Watching for bounce")

    items, summary = temp_service.get_watchlist_summary()
    assert len(items) == 1
    assert items[0].symbol == "TATACONSUM"
    assert "Watching for bounce" in summary


def test_audit_single_symbol(temp_service: ScannerService):
    res = temp_service.audit_single_symbol("NESTLEIND")
    assert res["symbol"] == "NESTLEIND"
    assert res["fundamental_audit"].passed_audit is True
    assert res["insider_activity"] is not None
    assert res["insider_activity"].is_material_promoter_buy is True


def test_daily_briefing_markdown_formatting(temp_service: ScannerService):
    dashboard = DailyDashboard52(
        as_of_date="2026-11-10",
        new_radar_signals=[
            CapitulationSignal(
                symbol="INFY",
                capitulation_date="2026-11-10",
                low_price=1400.0,
                high_price=1430.0,
                close_price=1410.0,
                today_volume=2000000,
                avg_volume_20d=500000,
                volume_ratio=4.0,
                support_sl=1400.0,
                target_1_20ema=1480.0,
                target_2_50ema=1540.0,
                audit=MockScreener().audit_company("INFY"),
                stage=SignalStage.RADAR,
            )
        ],
        watchlist_buy_triggers=[
            WatchlistStock(
                symbol="NESTLEIND",
                added_date="2026-11-08",
                capitulation_date="2026-11-08",
                capitulation_low=2100.0,
                capitulation_high=2180.0,
                target_1_20ema=2250.0,
                target_2_50ema=2380.0,
                is_buy_triggered=True,
                trigger_price=2190.0,
            )
        ],
        active_portfolio_status=[],
        material_insider_trades=[],
        summary_notes=["Test briefing"],
    )

    md = temp_service.format_daily_briefing_markdown(dashboard)
    assert "# 🎯 52-Week Low Capitulation Briefing" in md
    assert "NESTLEIND" in md
    assert "₹2190.00" in md
    assert "INFY" in md
    assert "4.00x" in md


def test_buy_and_sell_proxies(temp_service: ScannerService):
    pos = temp_service.record_buy(
        symbol="TCS",
        entry_price=3500.0,
        quantity=50,
        notes="Long term value dip",
    )
    assert pos.symbol == "TCS"
    assert pos.remaining_quantity == 50

    stock, archived = temp_service.record_sell(
        symbol="TCS",
        sell_price=3850.0,
        quantity=50,
        reason=SellReason.TARGET_1,
        notes="Booked full at target",
    )
    assert stock.remaining_quantity == 0
    assert archived is not None
    assert archived.net_return_pct == 10.0
    assert len(temp_service.tracker.get_portfolio()) == 0
    assert len(temp_service.tracker.get_trade_ledger()) == 1

