"""Unit and scenario tests for LowCapitulationScanner (Phase B)."""

import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from src.scanner.low_scanner import LowCapitulationScanner
from src.scanner.models import (
    CapitulationSignal,
    FundamentalAudit,
    InsiderTradeRecord,
    SignalStage,
    WatchlistStock,
)


def generate_synthetic_candles(
    n_bars: int = 260,
    base_price: float = 1000.0,
    downtrend: bool = True,
    anomaly_on_last_bar: bool = True,
    volume_multiplier: float = 4.5,
) -> pd.DataFrame:
    """Generate realistic daily OHLCV dataframe with known characteristics."""
    dates = pd.date_range(end="2026-11-10", periods=n_bars, freq="B", tz="Asia/Kolkata")
    
    # Generate prices
    prices = [base_price]
    for _ in range(n_bars - 1):
        step = -1.5 if downtrend else 1.0
        step += np.random.normal(0, 5)
        prices.append(max(10.0, prices[-1] + step))
        
    prices = np.array(prices)
    
    # If anomaly_on_last_bar, force last bar to be the lowest
    if anomaly_on_last_bar:
        prices[-1] = np.min(prices[:-1]) - 10.0
        
    lows = prices - 5.0
    highs = prices + 8.0
    opens = prices - 2.0
    closes = prices + 1.0
    
    # Volume: baseline ~100,000 shares
    volumes = np.random.normal(100_000, 10_000, n_bars)
    volumes = np.maximum(20_000, volumes)
    
    if anomaly_on_last_bar:
        # 20-day mean before last bar
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


class MockScreenerClient:
    def __init__(self, passed: bool = True):
        self.passed = passed
        
    def audit_company(self, symbol: str) -> FundamentalAudit:
        return FundamentalAudit(
            symbol=symbol,
            audit_date="2026-11-10",
            market_cap_cr=25000.0,
            current_price=500.0,
            pe_ratio=22.0,
            roce_pct=18.5,
            debt_to_equity=0.25,
            interest_coverage=8.5,
            cfo_last_yr_cr=1200.0,
            promoter_pledge_pct=0.0,
            passed_audit=self.passed,
            failure_reasons=[] if self.passed else ["Debt/Equity exceeds 0.60"],
        )


class MockInsiderFeed:
    def __init__(self, has_material_buy: bool = False):
        self.has_material_buy = has_material_buy
        
    def get_symbol_insider_activity(self, symbol: str):
        if self.has_material_buy:
            return InsiderTradeRecord(
                symbol=symbol,
                filing_date="2026-11-08",
                acquirer_name="Promoter Group Ltd",
                category="Promoter",
                acquisition_mode="Market Purchase",
                quantity=100_000,
                value_inr=50_000_000.0,
                percent_equity=0.12,
                is_material_promoter_buy=True,
            )
        return None


# -------------------------------------------------------------------------
# TESTS
# -------------------------------------------------------------------------

def test_calculate_technical_levels():
    df = generate_synthetic_candles(n_bars=60, anomaly_on_last_bar=True, volume_multiplier=5.0)
    levels = LowCapitulationScanner.calculate_technical_levels(df)
    
    assert "low_52w" in levels
    assert "vol_sma20" in levels
    assert "volume_ratio" in levels
    assert levels["volume_ratio"] >= 4.0
    assert levels["ema5"] > 0
    assert levels["ema20"] > 0
    assert levels["ema50"] > 0
    assert levels["today_low"] <= levels["low_52w"] * 1.005


def test_scan_candidate_success_radar():
    df = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=True, volume_multiplier=4.2)
    mock_screener = MockScreenerClient(passed=True)
    mock_insider = MockInsiderFeed(has_material_buy=True)
    
    scanner = LowCapitulationScanner(
        screener_client=mock_screener,
        insider_feed=mock_insider,
    )
    
    signal = scanner.scan_candidate(symbol="NESTLEIND", df=df)
    
    assert signal is not None
    assert signal.symbol == "NESTLEIND"
    assert signal.stage == SignalStage.RADAR
    assert signal.volume_ratio >= 3.8
    assert signal.support_sl == signal.low_price
    assert signal.target_1_20ema > 0
    assert signal.target_2_50ema > 0
    assert signal.audit.passed_audit is True
    assert signal.insider_activity is not None
    assert signal.insider_activity.is_material_promoter_buy is True


def test_scan_candidate_secondary_test_lookback():
    """Verify Wyckoff secondary test: 4x volume spike was 3 days ago, today re-tests low on normal volume."""
    df = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=False)
    # Put 4.5x volume spike on bar -4 (3 sessions ago)
    mean_vol = np.mean(df["volume"].iloc[-25:-5])
    df.iloc[-4, df.columns.get_loc("volume")] = int(mean_vol * 4.5)
    # Lowest price was on bar -4
    lowest_px = 100.0
    df.iloc[-4, df.columns.get_loc("low")] = lowest_px
    df.iloc[-4, df.columns.get_loc("close")] = lowest_px + 2.0
    
    # Today (bar -1) has normal volume (1.5x) but re-tests the low (100.5, within 1% of 100.0)
    df.iloc[-1, df.columns.get_loc("low")] = lowest_px + 0.5
    df.iloc[-1, df.columns.get_loc("close")] = lowest_px + 2.0
    df.iloc[-1, df.columns.get_loc("volume")] = int(mean_vol * 1.5)

    scanner = LowCapitulationScanner(
        screener_client=MockScreenerClient(passed=True),
        insider_feed=MockInsiderFeed(has_material_buy=False),
    )
    signal = scanner.scan_candidate(symbol="AIAENG", df=df)

    assert signal is not None
    assert signal.symbol == "AIAENG"
    assert signal.volume_ratio >= 4.0  # Captured the primary climax from 3 sessions ago
    assert signal.support_sl == lowest_px  # Anchored to the true capitulation low



def test_scan_candidate_rejected_by_low_volume():
    # Only 1.5x volume (fails >= 3.0x threshold)
    df = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=True, volume_multiplier=1.5)
    scanner = LowCapitulationScanner(
        screener_client=MockScreenerClient(passed=True),
        insider_feed=MockInsiderFeed(has_material_buy=False),
    )
    
    signal = scanner.scan_candidate(symbol="TATAMOTORS", df=df)
    assert signal is None


def test_scan_candidate_rejected_not_at_52w_low():
    # Last bar is higher than 52w low
    df = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=False)
    # Ensure last bar is well above minimum
    df.iloc[-1, df.columns.get_loc("low")] = df["low"].min() + 50.0
    
    scanner = LowCapitulationScanner(
        screener_client=MockScreenerClient(passed=True),
        insider_feed=MockInsiderFeed(has_material_buy=False),
    )
    signal = scanner.scan_candidate(symbol="INFY", df=df)
    assert signal is None


def test_scan_candidate_rejected_by_fundamental_audit():
    # Hits 52W low on 5x volume, but company is insolvent / high debt
    df = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=True, volume_multiplier=5.0)
    scanner = LowCapitulationScanner(
        screener_client=MockScreenerClient(passed=False),  # Audit FAILS
        insider_feed=MockInsiderFeed(has_material_buy=False),
    )
    signal = scanner.scan_candidate(symbol="JUNKCORP", df=df)
    assert signal is None


def test_run_funnel_scan_basket():
    df_good = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=True, volume_multiplier=4.0)
    df_weak_vol = generate_synthetic_candles(n_bars=260, anomaly_on_last_bar=True, volume_multiplier=1.2)
    
    scanner = LowCapitulationScanner(
        screener_client=MockScreenerClient(passed=True),
        insider_feed=MockInsiderFeed(has_material_buy=False),
    )
    
    # Mock candle fetching by patching scan_candidate
    signals = []
    for sym, d in [("GOODSTOCK", df_good), ("WEAKSTOCK", df_weak_vol)]:
        s = scanner.scan_candidate(symbol=sym, df=d)
        if s:
            signals.append(s)
            
    assert len(signals) == 1
    assert signals[0].symbol == "GOODSTOCK"


def test_evaluate_stage2_confirmation_states():
    cap_low = 100.0
    cap_high = 110.0
    ema5 = 106.0
    
    # Case 1: Broken low -> INVALIDATED
    bar_break = pd.Series({"open": 102.0, "high": 103.0, "low": 98.0, "close": 99.0})
    stage, px = LowCapitulationScanner.evaluate_stage2_confirmation(cap_low, cap_high, bar_break, ema5)
    assert stage == SignalStage.INVALIDATED
    assert px == 99.0
    
    # Case 2: Breakout above cap_high -> CONFIRMED_BUY
    bar_breakout = pd.Series({"open": 105.0, "high": 112.0, "low": 104.0, "close": 111.0})
    stage, px = LowCapitulationScanner.evaluate_stage2_confirmation(cap_low, cap_high, bar_breakout, ema5)
    assert stage == SignalStage.CONFIRMED_BUY
    assert px == 111.0
    
    # Case 3: Reclaimed 5 EMA (e.g. close=107 > ema5=106, even if < cap_high) -> CONFIRMED_BUY
    bar_ema = pd.Series({"open": 103.0, "high": 108.0, "low": 102.0, "close": 107.0})
    stage, px = LowCapitulationScanner.evaluate_stage2_confirmation(cap_low, cap_high, bar_ema, ema5)
    assert stage == SignalStage.CONFIRMED_BUY
    assert px == 107.0
    
    # Case 4: Consolidation inside range below 5 EMA -> RADAR
    bar_inside = pd.Series({"open": 102.0, "high": 105.0, "low": 101.0, "close": 104.0})
    stage, px = LowCapitulationScanner.evaluate_stage2_confirmation(cap_low, cap_high, bar_inside, ema5)
    assert stage == SignalStage.RADAR
    assert px is None


def test_check_watchlist():
    scanner = LowCapitulationScanner()
    
    watchlist = [
        WatchlistStock(
            symbol="STOCK_A",
            added_date="2026-11-08",
            capitulation_date="2026-11-08",
            capitulation_low=100.0,
            capitulation_high=110.0,
            target_1_20ema=120.0,
            target_2_50ema=130.0,
            is_buy_triggered=False,
        ),
        WatchlistStock(
            symbol="STOCK_B",
            added_date="2026-11-08",
            capitulation_date="2026-11-08",
            capitulation_low=200.0,
            capitulation_high=220.0,
            target_1_20ema=240.0,
            target_2_50ema=260.0,
            is_buy_triggered=False,
        ),
    ]
    
    # Mock data provider: STOCK_A breaks out, STOCK_B consolidates
    df_a = pd.DataFrame(
        {
            "open": [105.0] * 10,
            "high": [115.0] * 10,
            "low": [102.0] * 10,
            "close": [112.0] * 10,  # > 110.0 high
            "volume": [10000] * 10,
        },
        index=pd.date_range("2026-11-01", periods=10, freq="B"),
    )
    
    df_b = pd.DataFrame(
        {
            "open": [205.0] * 10,
            "high": [215.0] * 10,
            "low": [202.0] * 10,
            "close": [205.0] * 10,  # below 220 high, inside range
            "volume": [10000] * 10,
        },
        index=pd.date_range("2026-11-01", periods=10, freq="B"),
    )
    
    def mock_get_bars(sym: str):
        return df_a if sym == "STOCK_A" else df_b
        
    updated = scanner.check_watchlist(watchlist, mock_get_bars)
    
    assert len(updated) == 2
    assert updated[0].symbol == "STOCK_A"
    assert updated[0].is_buy_triggered is True
    assert updated[0].trigger_price == 112.0
    
    assert updated[1].symbol == "STOCK_B"
    assert updated[1].is_buy_triggered is False

