"""Unit tests for 52-Week High Exhaustion Short Strategy (Phase 1)."""

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.scanner.models import (
    ExhaustionShortSignal,
    ShortExitReason,
    ShortSignalStage,
    ShortWatchlistStock,
)
from src.scanner.short_scanner import HighExhaustionShortScanner
from src.scanner.short_tracker import ShortPortfolioTracker
from src.scanner.short_service import ShortScannerService
from src.scanner.unified_service import UnifiedScannerService


def generate_climax_candles(
    n_bars: int = 260,
    base_price: float = 1000.0,
    with_climax: bool = True,
    volume_multiplier: float = 4.5,
    upper_wick_ratio: float = 0.60,
    close_pos_ratio: float = 0.20,
    low_volume_ghost: bool = False,
) -> pd.DataFrame:
    """Generate realistic daily OHLCV dataframe with strong uptrend and Day 1 Climax trap."""
    dates = pd.date_range(end="2026-11-16", periods=n_bars, freq="B", tz="Asia/Kolkata")
    np.random.seed(42)

    # Strong parabolic uptrend
    prices = [base_price]
    for i in range(n_bars - 1):
        step = 2.5 + np.random.normal(0, 1.5)
        prices.append(prices[-1] + step)

    prices = np.array(prices)

    opens = prices - 2.0
    closes = prices + 1.0
    lows = prices - 4.0
    highs = prices + 6.0

    # Volume baseline: ~50,000 shares
    volumes = np.random.normal(50_000, 5_000, n_bars)
    volumes = np.maximum(10_000, volumes)

    if low_volume_ghost:
        volumes = np.full(n_bars, 10)  # 10 shares baseline

    if with_climax:
        # Climax push: surges up significantly to establish parabolic stretch
        last_low = float(prices[-1] + 10.0)
        last_high = float(np.max(highs[:-1]) + 250.0)
        rng = last_high - last_low

        # Upper wick >= 45% and close in bottom 40%
        last_close = last_low + (rng * close_pos_ratio)
        last_open = last_low + (rng * (close_pos_ratio + 0.05))

        highs[-1] = last_high
        lows[-1] = last_low
        opens[-1] = last_open
        closes[-1] = last_close

        mean_vol = np.mean(volumes[-21:-1])
        volumes[-1] = mean_vol * volume_multiplier

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes.astype(int),
        },
        index=dates,
    )
    return df


def test_climax_trap_detection():
    """Verify Day 1 Climax Trap is correctly detected with abnormal volume and rejection wick."""
    scanner = HighExhaustionShortScanner()
    df = generate_climax_candles(with_climax=True, volume_multiplier=4.0)

    signal = scanner.scan_candidate("TEST_CLIMAX", df=df)
    assert signal is not None, "Valid Day 1 Climax Trap should produce an ExhaustionShortSignal!"
    assert signal.symbol == "TEST_CLIMAX"
    assert signal.volume_ratio >= 3.0
    assert signal.upper_wick_pct >= 45.0
    assert signal.close_position_pct <= 40.0
    assert signal.stage == ShortSignalStage.RADAR_CLIMAX
    assert signal.target_1_mis < signal.climax_low


def test_rejection_of_healthy_breakout():
    """Verify that a healthy breakout (strong close, small upper wick) is rejected by short scanner."""
    scanner = HighExhaustionShortScanner()
    # Close near highs (close_pos_ratio=0.90, upper_wick_ratio=0.10)
    df = generate_climax_candles(with_climax=True, upper_wick_ratio=0.10, close_pos_ratio=0.90)

    signal = scanner.scan_candidate("HEALTHY_BREAKOUT", df=df)
    assert signal is None, "Healthy breakout with strong close should NOT trigger a short signal!"


def test_rejection_of_illiquid_ghost_stock():
    """Verify that an illiquid stock with high relative volume ratio (e.g. 45 vs 10 avg) is rejected."""
    scanner = HighExhaustionShortScanner()
    df = generate_climax_candles(with_climax=True, low_volume_ghost=True)

    signal = scanner.scan_candidate("GHOST_STOCK", df=df)
    assert signal is None, "Illiquid stock must be strictly rejected by the liquidity floor!"


def test_day2_breakdown_trigger():
    """Verify Day 2 breakdown trigger occurs when Day 2 low breaks Day 1 climax low."""
    stock = ShortWatchlistStock(
        symbol="TRAP_STOCK",
        added_date="2026-11-15",
        climax_date="2026-11-15",
        trigger_level_low=1000.0,
        invalidation_level_high=1080.0,
        target_1_mis=980.0,
        target_2_mis=960.0,
    )

    # Case 1: Day 2 cracks Day 1 low
    dates = pd.date_range(end="2026-11-16", periods=1, freq="B", tz="Asia/Kolkata")
    df_trigger = pd.DataFrame(
        {"open": [1010.0], "high": [1015.0], "low": [995.0], "close": [998.0], "volume": [50000]},
        index=dates,
    )

    stage, px, note = HighExhaustionShortScanner.evaluate_day2_breakdown(stock, df_trigger)
    assert stage == ShortSignalStage.TRIGGERED_MIS
    assert px is not None and px < 1000.0

    # Case 2: Day 2 breaks Day 1 high (invalidation)
    df_inval = pd.DataFrame(
        {"open": [1010.0], "high": [1085.0], "low": [1005.0], "close": [1082.0], "volume": [50000]},
        index=dates,
    )
    stage_inv, px_inv, note_inv = HighExhaustionShortScanner.evaluate_day2_breakdown(stock, df_inval)
    assert stage_inv == ShortSignalStage.INVALIDATED


def test_short_tracker_watchlist_and_ledger(tmp_path):
    """Test ShortPortfolioTracker tier 1 watchlist and tier 3 trade ledger operations."""
    tracker = ShortPortfolioTracker(data_dir=str(tmp_path))

    # Add to watchlist
    stock = tracker.add_to_watchlist(
        signal_or_symbol="XYZ",
        climax_low=500.0,
        climax_high=540.0,
        climax_date="2026-11-15",
        user_notes="Massive 5x volume climax",
    )
    assert stock.symbol == "XYZ"
    assert stock.trigger_level_low == 500.0
    assert len(tracker.get_watchlist()) == 1

    # Record completed short trade
    record = tracker.record_completed_short(
        symbol="XYZ",
        entry_price=498.0,
        exit_price=488.0,
        quantity=100,
        exit_reason=ShortExitReason.TARGET_1,
        trade_date="2026-11-16",
    )
    assert record.realized_pnl_inr == 1000.0  # (498 - 488) * 100
    assert record.realized_pnl_pct == pytest.approx(2.01, rel=1e-2)
    assert len(tracker.get_watchlist()) == 0  # Cleaned up from watchlist
    assert len(tracker.get_ledger()) == 1


def test_unified_multi_table_watchlist():
    """Verify that get_unified_watchlist automatically outputs 3 separate, cleanly labeled tables."""
    unified = UnifiedScannerService()
    wl_md = unified.get_unified_watchlist()

    assert "1. 52-Week LOW (Capitulation Rebounds — LONG)" in wl_md
    assert "2. 52-Week HIGH (Breakout Continuations — LONG)" in wl_md
    assert "3. 52-Week HIGH EXHAUSTION" in wl_md


def test_unified_multi_table_portfolio():
    """Verify that get_unified_portfolio automatically segregates Long Positional vs Short Intraday MIS."""
    unified = UnifiedScannerService()
    port_md = unified.get_unified_portfolio()

    assert "Positional Delivery Holdings (LONG)" in port_md
    assert "Active Intraday MIS Positions (SHORT — Exit before 03:10 PM)" in port_md


def test_day3_continuation_lifecycle(tmp_path):
    """Verify Day 2 breakdown rollover to Day 3 Continuation breakdown."""
    tracker = ShortPortfolioTracker(data_dir=str(tmp_path))

    # Day 1: Add climax stock
    stock = tracker.add_to_watchlist("FALLCO", climax_low=1000.0, climax_high=1100.0)
    assert stock.status == ShortSignalStage.RADAR_CLIMAX
    assert stock.trigger_level_low == 1000.0

    # Day 2: Simulates breaking 1000 and closing at 980 (Low 975, High 1005)
    day2_bar = pd.DataFrame(
        [{"open": 1002.0, "high": 1005.0, "low": 975.0, "close": 980.0, "volume": 2000000}],
        index=[pd.Timestamp("2026-11-14")],
    )

    stage, px, note = HighExhaustionShortScanner.evaluate_breakdown(stock, day2_bar)
    assert stage == ShortSignalStage.TRIGGERED_MIS
    assert px == 999.95

    # Check EOD continuation eligibility
    eod_stats = HighExhaustionShortScanner.evaluate_eod_continuation(stock, day2_bar)
    assert eod_stats is not None
    assert eod_stats["day2_low"] == 975.0
    assert eod_stats["day2_high"] == 1005.0

    # Roll over to Day 3 Continuation
    cont_stock = tracker.rollover_to_day3_continuation(
        "FALLCO",
        day2_low=eod_stats["day2_low"],
        day2_high=eod_stats["day2_high"],
        day2_close=eod_stats["day2_close"],
    )
    assert cont_stock.status == ShortSignalStage.RADAR_DAY3_CONTINUATION
    assert cont_stock.trigger_level_low == 975.0  # Day 3 trigger is Day 2 Low!
    assert cont_stock.is_continuation is True

    # Day 3: Price cracks 975 (Day 2 low)
    day3_bar = pd.DataFrame(
        [{"open": 978.0, "high": 980.0, "low": 960.0, "close": 965.0, "volume": 1500000}],
        index=[pd.Timestamp("2026-11-15")],
    )
    stage3, px3, note3 = HighExhaustionShortScanner.evaluate_breakdown(cont_stock, day3_bar)
    assert stage3 == ShortSignalStage.TRIGGERED_DAY3_MIS
    assert px3 == 974.95
    assert "Day 3 Continuation MIS Short TRIGGERED" in note3
