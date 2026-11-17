"""Technical Scanner & State Machine for 52-Week High Exhaustion Short Strategy (Phase 1).

Detects Wyckoff Upthrust After Distribution (UTAD) / Buying Climax traps at 52-week highs
and evaluates Day 2 Intraday MIS Breakdown confirmations.
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from src.scanner.models import (
    ExhaustionShortSignal,
    ShortExitReason,
    ShortSignalStage,
    ShortWatchlistStock,
)

logger = logging.getLogger(__name__)

# Constants for detection, thresholds, and liquidity floor
NSE_CACHE_TTL: int = 7200  # 2 hours in seconds
HIGH_PROXIMITY_TOLERANCE: float = 0.015  # Within 1.5% of 52W High
VOLUME_ANOMALY_FACTOR: float = 3.0  # Volume >= 3.0x 20-day SMA volume
MIN_UPPER_WICK_PCT: float = 45.0  # Upper shadow >= 45% of candle range
MAX_CLOSE_POSITION_PCT: float = 40.0  # Close in bottom 40% of candle range
MIN_PARABOLIC_EXTENSION_PCT: float = 10.0  # Close >= 10% above 50-day EMA (or climax high >= 15% above 50 EMA)
MIN_AVG_DAILY_VOLUME: int = 5_000  # Minimum 5,000 shares/day average volume (liquidity floor)
MIN_DAILY_TURNOVER_INR: float = 50_00_000.0  # Minimum ₹50 Lakhs turnover gate

_RANDOM_UAS: List[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class HighExhaustionShortScanner:
    """Detects Day 1 Climax Traps and Day 2 Breakdown confirmations for Intraday MIS Shorts."""

    NSE_52W_HIGH_URL = "https://www.nseindia.com/api/live-analysis-variations?index=high"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        cache_manager: Optional[Any] = None,
        cache_dir: str = "data/cache",
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        if cache_manager is None:
            try:
                from src.engine.smart_cache import SmartCacheManager
                self.cache_manager = SmartCacheManager(cache_dir=cache_dir, default_provider="yfinance")
            except Exception as e:
                logger.warning(f"Could not initialize default SmartCacheManager: {e}")
                self.cache_manager = None
        else:
            self.cache_manager = cache_manager

    # -------------------------------------------------------------------------
    # STEP 1: BROAD 52W-HIGH DISCOVERY
    # -------------------------------------------------------------------------

    def load_quality_universe_symbols(self) -> List[str]:
        """Load symbols from local quality universes (Nifty 500 / Nifty 200)."""
        symbols: List[str] = []
        for cfg_name in ["nifty500.csv", "nifty200.csv"]:
            cfg_path = Path("config") / cfg_name
            if cfg_path.exists():
                try:
                    import csv
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            series = (row.get("Series") or "").strip().upper()
                            if series and series != "EQ":
                                continue
                            sym = (row.get("Symbol") or "").strip().upper()
                            if sym and not sym.startswith("DUMMY") and sym not in symbols:
                                symbols.append(sym)
                except Exception as e:
                    logger.warning(f"Error reading {cfg_path}: {e}")
        return symbols

    def fetch_nse_52w_high_symbols(self, force_refresh: bool = False) -> List[str]:
        """Fetch list of symbols currently at or near 52-week high directly from NSE."""
        cache_file = self.cache_dir / "nse_52w_high_symbols.json"
        now = time.time()

        if not force_refresh and cache_file.exists():
            try:
                mtime = os.path.getmtime(cache_file)
                if (now - mtime) < NSE_CACHE_TTL:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)
                        if isinstance(cached_data, list) and cached_data:
                            return cached_data
            except Exception as e:
                logger.warning(f"Failed to read 52W high cache: {e}")

        symbols_set: set[str] = set()
        ua = random.choice(_RANDOM_UAS) if _RANDOM_UAS else self.DEFAULT_USER_AGENT

        try:
            s = requests.Session()
            s.headers.update(
                {
                    "User-Agent": ua,
                    "Accept": "*/*",
                    "Referer": "https://www.nseindia.com",
                }
            )
            try:
                s.get("https://www.nseindia.com", timeout=6)
            except Exception:
                pass

            r_gainers = s.get("https://www.nseindia.com/api/live-analysis-variations?index=gainers", timeout=10)
            if r_gainers.status_code == 200:
                d_gainers = r_gainers.json()
                if isinstance(d_gainers, dict):
                    for sec, sec_data in d_gainers.items():
                        if isinstance(sec_data, dict):
                            for it in sec_data.get("data", []):
                                if isinstance(it, dict):
                                    sym = it.get("symbol")
                                    near_wkh = it.get("nearWKH")
                                    if sym and near_wkh is not None:
                                        try:
                                            if float(near_wkh) <= 10.0:
                                                symbols_set.add(sym.strip().upper())
                                        except (ValueError, TypeError):
                                            pass

            if not symbols_set:
                resp = s.get(self.NSE_52W_HIGH_URL, timeout=10)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    for item in data:
                        sym = item.get("symbol")
                        if sym:
                            symbols_set.add(sym.strip().upper())
        except Exception as e:
            logger.warning(f"NSE 52W-high fetch failed: {e}")

        if symbols_set:
            symbols_list = sorted(list(symbols_set))
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(symbols_list, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write 52W high cache: {e}")
            return symbols_list

        return self.load_quality_universe_symbols()

    # -------------------------------------------------------------------------
    # STEP 2: TECHNICAL METRICS COMPUTATION
    # -------------------------------------------------------------------------

    @staticmethod
    def calculate_technical_levels(df: pd.DataFrame) -> Dict[str, float]:
        """Compute rolling 52W high, volume SMA, EMAs, and candlestick geometry."""
        if df.empty or len(df) < 20:
            raise ValueError(f"Insufficient candle history ({len(df)} bars, need >= 20)")

        d = df.copy()
        d.columns = [str(c).lower() for c in d.columns]

        roll_window = min(252, len(d))
        prior_52w_high = float(d["high"].shift(1).rolling(window=roll_window - 1, min_periods=20).max().iloc[-1])
        high_52w = float(d["high"].rolling(window=roll_window, min_periods=20).max().iloc[-1])

        vol_sma20_series = d["volume"].shift(1).rolling(window=20, min_periods=5).mean()
        vol_sma20 = float(vol_sma20_series.iloc[-1])
        vol_today = float(d["volume"].iloc[-1])
        vol_ratio = round(vol_today / vol_sma20, 2) if vol_sma20 > 0 else 1.0

        ema50 = float(d["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        last_bar = d.iloc[-1]

        today_open = float(last_bar["open"])
        today_high = float(last_bar["high"])
        today_low = float(last_bar["low"])
        today_close = float(last_bar["close"])

        candle_range = max(today_high - today_low, 0.01)
        upper_wick = today_high - max(today_open, today_close)
        upper_wick_pct = round((upper_wick / candle_range) * 100, 2)
        close_pos_pct = round(((today_close - today_low) / candle_range) * 100, 2)

        parabolic_ext_pct = round(((today_close - ema50) / ema50) * 100, 2) if ema50 > 0 else 0.0

        today_turnover = float(vol_today * today_close)
        avg_turnover = float(vol_sma20 * today_close)

        return {
            "prior_52w_high": prior_52w_high,
            "high_52w": high_52w,
            "vol_sma20": vol_sma20,
            "today_volume": int(vol_today),
            "today_turnover": today_turnover,
            "avg_turnover": avg_turnover,
            "volume_ratio": vol_ratio,
            "today_open": today_open,
            "today_high": today_high,
            "today_low": today_low,
            "today_close": today_close,
            "ema50": round(ema50, 2),
            "upper_wick_pct": upper_wick_pct,
            "close_pos_pct": close_pos_pct,
            "parabolic_ext_pct": parabolic_ext_pct,
        }

    # -------------------------------------------------------------------------
    # STEP 3: DAY 1 CLIMAX CANDIDATE SCANNER (STAGE 1 RADAR)
    # -------------------------------------------------------------------------

    def scan_candidate(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        as_of_date: Optional[str] = None,
    ) -> Optional[ExhaustionShortSignal]:
        """Scan a candidate symbol to evaluate if it printed a Day 1 Climax Trap."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")

        if df is None:
            if self.cache_manager is None:
                raise ValueError("No DataFrame provided and no cache_manager configured.")
            if as_of_date:
                end_d = as_of_date
                start_d = (pd.to_datetime(end_d) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
                df = self.cache_manager.get_candles(
                    symbol=clean_sym,
                    exchange="NSE",
                    interval="1d",
                    start_date=start_d,
                    end_date=end_d,
                )
            else:
                df = self.cache_manager.get_candles(
                    symbol=clean_sym,
                    exchange="NSE",
                    interval="1d",
                )

        if df is None or len(df) < 20:
            return None

        if as_of_date:
            as_of_ts = pd.to_datetime(as_of_date)
            if df.index.tz is not None and as_of_ts.tz is None:
                as_of_ts = as_of_ts.tz_localize(df.index.tz)
            df = df.loc[df.index <= as_of_ts]
            if df.empty or len(df) < 20:
                return None

        try:
            tech = self.calculate_technical_levels(df)
        except ValueError:
            return None

        # 1. 52W High Proximity: Intraday high touched 52W high
        today_high = tech["today_high"]
        high_52w = tech["high_52w"]
        prior_52w_high = tech["prior_52w_high"]

        touched_high = (today_high >= (prior_52w_high * (1.0 - HIGH_PROXIMITY_TOLERANCE))) or (today_high >= high_52w * 0.99)
        if not touched_high:
            return None

        # 2. Institutional Liquidity Floor (Prevents illiquid ghost stocks)
        avg_vol = tech["vol_sma20"]
        today_turnover = tech.get("today_turnover", 0.0)
        avg_turnover = tech.get("avg_turnover", 0.0)
        if avg_vol < MIN_AVG_DAILY_VOLUME or (today_turnover < MIN_DAILY_TURNOVER_INR and avg_turnover < MIN_DAILY_TURNOVER_INR):
            return None

        # 3. Volume Anomaly: Abnormal institutional volume surge (>= 3.0x)
        vol_ratio = tech["volume_ratio"]
        if vol_ratio < VOLUME_ANOMALY_FACTOR:
            return None

        # 4. Candlestick Geometry: Severe Upper Rejection Wick (>= 45%) & Weak Close (<= 40%)
        upper_wick_pct = tech["upper_wick_pct"]
        close_pos_pct = tech["close_pos_pct"]
        if upper_wick_pct < MIN_UPPER_WICK_PCT or close_pos_pct > MAX_CLOSE_POSITION_PCT:
            return None

        # 5. Parabolic Stretch Check (Climax high >= 15% or close >= 10% above 50 EMA)
        high_ext = round(((today_high - tech["ema50"]) / tech["ema50"]) * 100, 2) if tech["ema50"] > 0 else 0.0
        parabolic_ext = tech["parabolic_ext_pct"]
        if parabolic_ext < MIN_PARABOLIC_EXTENSION_PCT and high_ext < 15.0:
            return None

        climax_low = tech["today_low"]
        climax_high = tech["today_high"]
        initial_sl = round(climax_high * 1.003, 2)
        t1_mis = round(climax_low * 0.98, 2)  # -2.0%
        t2_mis = round(climax_low * 0.96, 2)  # -4.0%
        dt_str = df.index[-1].strftime("%Y-%m-%d")

        return ExhaustionShortSignal(
            symbol=clean_sym,
            climax_date=dt_str,
            climax_high=climax_high,
            climax_low=climax_low,
            climax_close=tech["today_close"],
            today_volume=tech["today_volume"],
            avg_volume_20d=tech["vol_sma20"],
            volume_ratio=vol_ratio,
            upper_wick_pct=upper_wick_pct,
            close_position_pct=close_pos_pct,
            parabolic_extension_pct=parabolic_ext,
            initial_sl=initial_sl,
            target_1_mis=t1_mis,
            target_2_mis=t2_mis,
            stage=ShortSignalStage.RADAR_CLIMAX,
        )

    # -------------------------------------------------------------------------
    # STEP 4: DAY 2 & DAY 3 INTRADAY BREAKDOWN EVALUATOR
    # -------------------------------------------------------------------------

    @staticmethod
    def evaluate_breakdown(
        stock: ShortWatchlistStock,
        candle_df: pd.DataFrame,
    ) -> Tuple[ShortSignalStage, Optional[float], str]:
        """Evaluate whether a watchlist stock triggered Day 2 initial breakdown or Day 3 continuation short.
        
        Returns:
            Tuple of (NewStage, ExecutionPrice, RationaleNote)
        """
        if candle_df.empty:
            return stock.status, None, "No price data"

        d = candle_df.copy()
        d.columns = [str(c).lower() for c in d.columns]
        last_bar = d.iloc[-1]

        bar_high = float(last_bar["high"])
        bar_low = float(last_bar["low"])
        trigger_low = stock.trigger_level_low
        invalidation_high = stock.invalidation_level_high

        # 1. Check Invalidation: Price exceeded resistance/invalidation high
        if bar_high >= invalidation_high:
            note = f"Setup INVALIDATED: Price exceeded invalidation high (₹{bar_high:.2f} >= ₹{invalidation_high:.2f})."
            return ShortSignalStage.INVALIDATED, bar_high, note

        # 2. Check Breakdown Trigger: Price broke trigger low
        if bar_low <= trigger_low:
            exec_px = round(trigger_low - 0.05, 2)
            if stock.status == ShortSignalStage.RADAR_DAY3_CONTINUATION or stock.is_continuation:
                stage = ShortSignalStage.TRIGGERED_DAY3_MIS
                note = f"Day 3 Continuation MIS Short TRIGGERED @ ₹{exec_px:.2f} (Cracked Day 2 Low ₹{trigger_low:.2f})."
            else:
                stage = ShortSignalStage.TRIGGERED_MIS
                note = f"Day 2 Intraday MIS Short TRIGGERED @ ₹{exec_px:.2f} (Cracked Day 1 Climax Low ₹{trigger_low:.2f})."
            return stage, exec_px, note

        target_name = "Day 2" if stock.is_continuation else "Day 1"
        return stock.status, None, f"Awaiting breakdown below {target_name} Low ₹{trigger_low:.2f}."

    # Backwards-compatible alias for Day 2 evaluations
    evaluate_day2_breakdown = evaluate_breakdown

    @staticmethod
    def evaluate_eod_continuation(
        stock: ShortWatchlistStock,
        day2_df: pd.DataFrame,
    ) -> Optional[Dict[str, float]]:
        """At Day 2 EOD (3:30 PM), check if Day 2 closed weak enough to warrant Day 3 continuation short."""
        if day2_df.empty:
            return None
        d = day2_df.copy()
        d.columns = [str(c).lower() for c in d.columns]
        last_bar = d.iloc[-1]
        c = float(last_bar["close"])
        o = float(last_bar["open"])
        h = float(last_bar["high"])
        l = float(last_bar["low"])

        # Continuation criteria: closed red (close <= open), closed below trigger level, and weak close in lower 45% of range
        rng = max(0.01, h - l)
        close_pos = (c - l) / rng
        if c <= o and c <= stock.trigger_level_low and close_pos <= 0.45:
            return {"day2_low": l, "day2_high": h, "day2_close": c}
        return None
