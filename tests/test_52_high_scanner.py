"""Unit and scenario tests for HighBreakoutScanner (52-Week High Strategy)."""

from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.scanner.high_scanner import HighBreakoutScanner
from src.scanner.models import (
    BreakoutSignal,
    BreakoutStage,
    FundamentalAudit,
    HighWatchlistStock,
)


def generate_breakout_candles(
    n_bars: int = 260,
    base_price: float = 1000.0,
    with_base: bool = True,
    base_depth_pct: float = 12.0,
    breakout_on_last_bar: bool = True,
    volume_multiplier: float = 3.5,
    severe_upper_wick: bool = False,
    parabolic: bool = False,
) -> pd.DataFrame:
    """Generate realistic daily OHLCV dataframe with uptrend, consolidation base, and breakout."""
    dates = pd.date_range(end="2026-11-10", periods=n_bars, freq="B", tz="Asia/Kolkata")
    np.random.seed(42)

    # Steady upward trend to establish Stage 2 rising 200 SMA
    prices = [base_price]
    for i in range(n_bars - 1):
        if with_base and (n_bars - 50 <= i < n_bars - 1):
            # 50-day consolidation base: small oscillations with controlled depth
            cycle = np.sin((i - (n_bars - 50)) / 5.0) * (base_price * (base_depth_pct / 200.0))
            p = base_price * 1.3 - (base_price * (base_depth_pct / 200.0)) + cycle
            prices.append(p)
        else:
            step = 1.8 if not parabolic else 8.0
            prices.append(prices[-1] + step + np.random.normal(0, 2))

    prices = np.array(prices)

    if breakout_on_last_bar:
        # Highest high of the dataset
        prices[-1] = np.max(prices[:-1]) + 5.0

    opens = prices - 2.0
    closes = prices + 1.0
    lows = prices - 4.0
    highs = prices + 6.0

    if severe_upper_wick:
        # Huge upper shadow
        highs[-1] = closes[-1] + 50.0
        lows[-1] = closes[-1] - 5.0
        opens[-1] = closes[-1] - 2.0

    # Volume baseline ~100k
    volumes = np.random.normal(100_000, 10_000, n_bars)
    volumes = np.maximum(20_000, volumes)

    if breakout_on_last_bar:
        mean_vol = np.mean(volumes[-21:-1])
        volumes[-1] = mean_vol * volume_multiplier

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    return df


class MockCacheManager:
    def __init__(self, dfs):
        self.dfs = dfs

    def get_candles(self, symbol, exchange, interval, start_date, end_date):
        return self.dfs.get(symbol)


class MockScreenerClient:
    def __init__(self, pass_growth=True):
        self.pass_growth = pass_growth

    def audit_growth_company(self, symbol: str, force_refresh: bool = False):
        return FundamentalAudit(
            symbol=symbol,
            audit_date="2026-11-10",
            market_cap_cr=25000.0,
            current_price=1200.0,
            pe_ratio=35.0,
            roce_pct=18.5,
            roe_pct=16.0,
            debt_to_equity=0.35,
            interest_coverage=8.0,
            cfo_last_yr_cr=500.0,
            promoter_holding_pct=58.0,
            promoter_pledge_pct=0.0,
            sales_growth_yoy_pct=15.2,
            profit_growth_yoy_pct=22.0,
            passed_audit=self.pass_growth,
            failure_reasons=[] if self.pass_growth else ["ROCE is 8.0% (Must be >= 12.0%)"],
        )


class MockInsiderFeed:
    def get_symbol_insider_activity(self, symbol: str):
        return None

    def get_recent_material_promoter_buys(self, days_lookback: int = 7):
        return []


# -------------------------------------------------------------------------
# TESTS
# -------------------------------------------------------------------------

def test_calculate_technical_levels():
    """Verify technical calculation outputs for breakout engine."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, volume_multiplier=3.5)
    tech = HighBreakoutScanner.calculate_technical_levels(df)

    assert "high_52w" in tech
    assert "vol_sma20" in tech
    assert "volume_ratio" in tech
    assert "atr14" in tech
    assert "sma150" in tech
    assert "sma200" in tech
    assert tech["volume_ratio"] >= 3.0
    assert tech["today_close"] <= tech["high_52w"]


def test_detect_consolidation_base_healthy():
    """Verify a healthy 12% depth base with rising 200 SMA passes base check."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, with_base=True, base_depth_pct=12.0)
    base = HighBreakoutScanner.detect_consolidation_base(df)

    assert base.passed_base_check is True
    assert base.base_depth_pct <= 20.0
    assert base.above_150_sma is True
    assert base.above_200_sma is True
    assert base.rising_200_sma is True


def test_detect_consolidation_base_too_deep_fails():
    """Verify a base with excessive drawdown (> 20%) is rejected."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, with_base=True, base_depth_pct=35.0)
    base = HighBreakoutScanner.detect_consolidation_base(df)

    assert base.passed_base_check is False
    assert any("Base depth" in r for r in base.failure_reasons)


def test_detect_exhaustion_climax_rejection_wick():
    """Verify a candle with a massive upper shadow triggers exhaustion guard."""
    df = generate_breakout_candles(n_bars=260, severe_upper_wick=True)
    exhaustion = HighBreakoutScanner.detect_exhaustion_climax(df)

    assert exhaustion.has_rejection_wick is True
    assert exhaustion.close_in_lower_half is True
    assert exhaustion.exhaustion_score >= 2
    assert exhaustion.is_exhausted is True


def test_scan_candidate_success():
    """End-to-end qualification of a valid 52W high breakout."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, volume_multiplier=3.0)
    scanner = HighBreakoutScanner(
        cache_manager=MockCacheManager({"TRENT": df}),
        screener_client=MockScreenerClient(pass_growth=True),
        insider_feed=MockInsiderFeed(),
    )

    signal = scanner.scan_candidate("TRENT", df=df)
    assert signal is not None
    assert signal.symbol == "TRENT"
    assert signal.stage == BreakoutStage.RADAR
    assert signal.volume_ratio >= 2.0
    assert signal.initial_sl < signal.breakout_price
    assert signal.target_1_15pct > signal.breakout_price
    assert signal.target_2_30pct > signal.target_1_15pct
    assert signal.audit.passed_audit is True


def test_scan_candidate_rejected_by_fundamentals():
    """Verify fundamental failure vetoes the technical breakout."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, volume_multiplier=3.0)
    scanner = HighBreakoutScanner(
        cache_manager=MockCacheManager({"TRAP": df}),
        screener_client=MockScreenerClient(pass_growth=False),
        insider_feed=MockInsiderFeed(),
    )

    signal = scanner.scan_candidate("TRAP", df=df)
    assert signal is None


def test_scan_candidate_rejected_by_low_volume():
    """Verify breakouts lacking institutional volume (< 2.0x) are rejected."""
    df = generate_breakout_candles(n_bars=260, base_price=1000.0, volume_multiplier=1.2)
    scanner = HighBreakoutScanner(
        cache_manager=MockCacheManager({"QUIET": df}),
        screener_client=MockScreenerClient(pass_growth=True),
        insider_feed=MockInsiderFeed(),
    )

    signal = scanner.scan_candidate("QUIET", df=df)
    assert signal is None


def test_evaluate_stage2_confirmation_confirmed():
    """Follow-through close above pivot high confirms Stage 2 Buy."""
    pivot_high = 1050.0
    initial_sl = 990.0

    ft_bar = pd.Series({"open": 1045.0, "high": 1070.0, "low": 1040.0, "close": 1065.0, "volume": 150000})
    stage, trigger_px = HighBreakoutScanner.evaluate_stage2_confirmation(
        pivot_high=pivot_high,
        initial_sl=initial_sl,
        follow_through_bar=ft_bar,
    )
    assert stage == BreakoutStage.CONFIRMED_BUY
    assert trigger_px == 1065.0


def test_evaluate_stage2_confirmation_invalidated():
    """Follow-through close below initial SL invalidates the breakout."""
    pivot_high = 1050.0
    initial_sl = 990.0

    ft_bar = pd.Series({"open": 1010.0, "high": 1015.0, "low": 970.0, "close": 980.0, "volume": 200000})
    stage, trigger_px = HighBreakoutScanner.evaluate_stage2_confirmation(
        pivot_high=pivot_high,
        initial_sl=initial_sl,
        follow_through_bar=ft_bar,
    )
    assert stage == BreakoutStage.INVALIDATED
    assert trigger_px == 980.0


def test_check_watchlist():
    """Verify check_watchlist updates triggered stocks."""
    scanner = HighBreakoutScanner()
    w_stock = HighWatchlistStock(
        symbol="BEL",
        added_date="2026-11-05",
        breakout_date="2026-11-05",
        breakout_price=300.0,
        pivot_high=305.0,
        initial_sl=285.0,
        trailing_20ema=290.0,
        target_1_15pct=345.0,
        target_2_30pct=390.0,
    )

    ft_df = pd.DataFrame(
        {
            "open": [304.0],
            "high": [315.0],
            "low": [303.0],
            "close": [312.0],
            "volume": [250000],
        },
        index=[pd.to_datetime("2026-11-06", utc=True)],
    )

    updated = scanner.check_watchlist([w_stock], get_daily_bars_fn=lambda sym: ft_df)
    assert len(updated) == 1
    assert updated[0].is_buy_triggered is True
    assert updated[0].trigger_price == 312.0
    assert any("BUY CONFIRMED" in note for note in updated[0].history_notes)
