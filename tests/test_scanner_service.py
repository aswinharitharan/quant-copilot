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


class MockCacheManager:
    def __init__(self, candles_by_symbol: Optional[Dict[str, pd.DataFrame]] = None):
        self.candles_by_symbol = candles_by_symbol or {}

    def get_candles(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "1d",
        start_date: str = "2026-01-01",
        end_date: str = "2026-12-31",
    ) -> pd.DataFrame:
        return self.candles_by_symbol.get(symbol.upper(), pd.DataFrame())


@pytest.fixture
def temp_service(tmp_path: Path) -> ScannerService:
    cache_d = tmp_path / "cache"
    data_d = tmp_path / "data"
    cache_d.mkdir()
    data_d.mkdir()

    return ScannerService(
        cache_dir=str(cache_d),
        data_dir=str(data_d),
        cache_manager=MockCacheManager(),
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


def test_portfolio_and_watchlist_auto_fetch_latest_prices(tmp_path: Path):
    """Verify portfolio and watchlist summaries automatically fetch latest prices & Stage 2 triggers."""
    cache_d = tmp_path / "cache"
    data_d = tmp_path / "data"
    cache_d.mkdir()
    data_d.mkdir()

    dates = pd.date_range("2026-11-10", "2026-11-12", freq="D", tz="Asia/Kolkata")
    piind_df = pd.DataFrame(
        {
            "open": [1741.0, 1727.0, 1744.0],
            "high": [1742.2, 1776.0, 1778.8],
            "low": [1699.4, 1715.0, 1730.0],
            "close": [1712.9, 1761.0, 1740.2],
            "volume": [1608101, 1529465, 1119491],
        },
        index=dates,
    )
    aia_df = pd.DataFrame(
        {
            "open": [3190.1, 3160.0, 3170.0],
            "high": [3204.9, 3201.9, 3214.5],
            "low": [3082.7, 3130.0, 3160.0],
            "close": [3136.4, 3167.2, 3205.7],
            "volume": [187765, 97066, 96738],
        },
        index=dates,
    )

    service = ScannerService(
        cache_dir=str(cache_d),
        data_dir=str(data_d),
        cache_manager=MockCacheManager({"PIIND": piind_df, "AIAENG": aia_df}),
        screener_client=MockScreener(),
        insider_feed=MockInsider(),
    )

    # Register PIIND buy @ 1773.60 (with capitulation_low=1699.40)
    service.tracker.record_buy(
        symbol="PIIND",
        entry_price=1773.60,
        quantity=6,
        entry_date="2026-11-11",
        capitulation_low=1699.40,
        target_1_20ema=2047.79,
        target_2_50ema=2210.95,
    )

    # Add AIAENG to watchlist (capitulation_high=3204.90)
    sig_aia = CapitulationSignal(
        symbol="AIAENG",
        capitulation_date="2026-11-10",
        low_price=3082.70,
        high_price=3204.90,
        close_price=3136.40,
        today_volume=187765,
        avg_volume_20d=97866.0,
        volume_ratio=1.92,
        support_sl=3082.70,
        target_1_20ema=3499.94,
        target_2_50ema=3776.47,
        audit=MockScreener().audit_company("AIAENG"),
        stage=SignalStage.RADAR,
    )
    service.tracker.add_to_watchlist(sig_aia, added_date="2026-11-10")

    # 1. Portfolio summary WITHOUT explicit current_prices should auto-fetch 1740.20
    portfolio, port_md = service.get_portfolio_summary(as_of_date="2026-11-12")
    assert len(portfolio) == 1
    assert portfolio[0].current_price == 1740.20
    assert portfolio[0].unrealized_pnl_pct == pytest.approx(-1.88, abs=0.05)
    assert "₹1740.20" in port_md

    # 2. Watchlist summary should auto-evaluate Stage 2 trigger (3205.70 > 3204.90)
    watchlist, watch_md = service.get_watchlist_summary(as_of_date="2026-11-12")
    assert len(watchlist) == 1
    assert watchlist[0].is_buy_triggered is True
    assert watchlist[0].trigger_date == "2026-11-12"
    assert watchlist[0].trigger_price == pytest.approx(3205.70, abs=0.01)
    assert "BUY TRIGGERED" in watch_md
    assert "₹3205.70" in watch_md

    # 3. Daily briefing WITHOUT explicit current_prices should also reflect updated portfolio & triggered watchlist
    dashboard = service.get_daily_briefing(candidate_symbols=[], as_of_date="2026-11-12")
    assert dashboard.active_portfolio_status[0].current_price == 1740.20
    assert len(dashboard.watchlist_buy_triggers) == 1
    assert dashboard.watchlist_buy_triggers[0].symbol == "AIAENG"


def test_add_and_remove_watchlist_via_service(tmp_path: Path):
    """Verify ScannerService.add_to_watchlist and remove_from_watchlist facade methods."""
    cache_d = tmp_path / "cache"
    data_d = tmp_path / "data"
    cache_d.mkdir()
    data_d.mkdir()

    dates = pd.date_range(end="2026-11-12", periods=30, freq="B", tz="Asia/Kolkata")
    closes = [3000.0 - i * 10 for i in range(30)]
    lows = [c - 20.0 for c in closes]
    highs = [c + 30.0 for c in closes]
    vols = [100_000] * 29 + [500_000]  # 5x anomaly on last day
    df = pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=dates,
    )

    service = ScannerService(
        cache_dir=str(cache_d),
        data_dir=str(data_d),
        cache_manager=MockCacheManager({"THERMAX": df}),
        screener_client=MockScreener(),
        insider_feed=MockInsider(),
    )

    added = service.add_to_watchlist("THERMAX", user_notes="5x climax", as_of_date="2026-11-12")
    assert added is not None
    assert added.symbol == "THERMAX"
    assert added.added_date == "2026-11-12"
    assert len(service.tracker.get_watchlist()) == 1

    assert service.remove_from_watchlist("THERMAX") is True
    assert len(service.tracker.get_watchlist()) == 0
    assert service.remove_from_watchlist("THERMAX") is False


def test_symbol_whitelist_validation(temp_service: ScannerService):
    """Verify whitelist regex rejects invalid symbols (e.g. punctuation, symbols, whitespace)."""
    assert temp_service.add_to_watchlist("INVALID$") is None
    assert temp_service.add_to_watchlist("AAPL.NS;DROP TABLE") is None
    assert temp_service.add_to_watchlist("") is None
    assert temp_service.add_to_watchlist("TOOLONGTICKERNAMEEXCEEDINGLIMIT") is None


def test_offline_mode_skips_price_fetch_and_renders_na(tmp_path: Path):
    """Verify --offline mode (current_prices={}) skips price auto-fetch and renders 'price N/A'."""
    cache_d = tmp_path / "cache"
    data_d = tmp_path / "data"
    cache_d.mkdir()
    data_d.mkdir()

    service = ScannerService(
        cache_dir=str(cache_d),
        data_dir=str(data_d),
        cache_manager=MockCacheManager(),
        screener_client=MockScreener(),
        insider_feed=MockInsider(),
    )

    # Record buy to create an active holding
    service.record_buy("PIIND", entry_price=1750.0, quantity=10, entry_date="2026-11-10")

    # 1. Calling get_portfolio_summary with current_prices={}
    stocks, summary_md = service.get_portfolio_summary(current_prices={})
    assert len(stocks) == 1
    assert "Current: price N/A" in summary_md

    # 2. Calling get_daily_briefing with current_prices={}
    dashboard = service.get_daily_briefing(candidate_symbols=[], current_prices={})
    assert any("Offline mode" in s for s in dashboard.summary_notes)

    briefing_md = service.format_daily_briefing_markdown(dashboard)
    assert "price N/A" in briefing_md


