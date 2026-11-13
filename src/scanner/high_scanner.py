"""52-Week High Technical Engine & State Machine (Institutional Breakout Accumulation).

Implements the 4-Layer Institutional Breakout Funnel:
1. 52-Week High Proximity (Close within 3% of rolling 252-day high or fresh 52W high in T-5 days)
2. Base Structure & VCP Check (15-60 days consolidation, base depth <= 20%, ATR contraction <= 0.80, Stage 2 rising 200 SMA)
3. Institutional Volume Confirmation (Volume >= 2.0x 20-day SMA, but <= 20x)
4. Negative Filter: Exhaustion Climax Guard (Vetoes blowoff tops / parabolic runs / severe upper wicks)
5. Fundamental Growth Screen (Screener.in growth rules: Sales, Profit, ROCE, D/E, Promoter pledge/holding)
6. Stage 2 Follow-Through State Machine (T+1 to T+5 confirmation above breakout high)
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
    BreakoutSignal,
    BreakoutStage,
    ConsolidationBaseMetrics,
    ExhaustionMetrics,
    FundamentalAudit,
    HighWatchlistStock,
    InsiderTradeRecord,
)
from src.scanner.screener_client import ScreenerClient
from src.scanner.insider_feed import InsiderFeed

logger = logging.getLogger(__name__)

# Constants for discovery, caching, and technical rules
NSE_CACHE_TTL: int = 7200  # 2 hours in seconds
BREAKOUT_PROXIMITY_TOLERANCE: float = 0.03  # Close within 3% of 52W high
VOLUME_ANOMALY_FACTOR: float = 2.0  # >= 2.0x 20-day SMA volume
MAX_VOLUME_CEILING: float = 20.0  # <= 20x to avoid blowoff tops
MAX_BASE_DEPTH_PCT: float = 20.0  # Max 20% drawdown in consolidation base
MAX_ATR_CONTRACTION_RATIO: float = 0.80  # ATR at breakout <= 80% of ATR at base start
TARGET_1_PCT: float = 0.15  # +15% Target 1
TARGET_2_PCT: float = 0.30  # +30% Target 2
MAX_INITIAL_SL_PCT: float = 0.06  # Maximum 6% initial stop loss buffer

_RANDOM_UAS: List[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class HighBreakoutScanner:
    """Technical scanner and two-stage state machine for 52-Week High Breakout Strategy."""

    NSE_52W_HIGH_URL = "https://www.nseindia.com/api/live-analysis-variations?index=high"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        cache_manager: Optional[Any] = None,
        screener_client: Optional[ScreenerClient] = None,
        insider_feed: Optional[InsiderFeed] = None,
        cache_dir: str = "data/cache",
    ):
        self.cache_manager = cache_manager
        self.screener = screener_client or ScreenerClient(cache_dir=cache_dir)
        self.insider = insider_feed or InsiderFeed(cache_dir=cache_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # STEP 1: BROAD 52W-HIGH DISCOVERY
    # -------------------------------------------------------------------------

    def load_quality_universe_symbols(self) -> List[str]:
        """Load symbols from local quality universes (Nifty 500 / Nifty 200).
        
        Ensures steady compounders breaking out into 52W highs without making
        volatile Top Gainer lists are never missed.
        """
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
        """Fetch list of symbols currently at or near 52-week high directly from NSE.
        
        Cached locally for NSE_CACHE_TTL seconds. Queries NSE live variations endpoint
        to identify stocks within 10% of their 52-week high.
        """
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

            # Primary: Live analysis variations gainers near 52W high
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
                                    # Candidate if within 10% of 52-week high
                                    if sym and near_wkh is not None:
                                        try:
                                            if float(near_wkh) <= 10.0:
                                                symbols_set.add(sym.strip().upper())
                                        except (ValueError, TypeError):
                                            pass
            else:
                logger.warning(f"NSE variations gainers status: {r_gainers.status_code}")

            # Secondary fallback: legacy endpoint if variations didn't return symbols
            if not symbols_set:
                resp = s.get(self.NSE_52W_HIGH_URL, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_list = []
                    if isinstance(data, dict):
                        if isinstance(data.get("data"), list):
                            raw_list = data["data"]
                        elif isinstance(data.get("NIFTY"), dict) and isinstance(data["NIFTY"].get("data"), list):
                            raw_list = data["NIFTY"]["data"]
                    elif isinstance(data, list):
                        raw_list = data

                    for item in raw_list:
                        if isinstance(item, dict):
                            sym = item.get("symbol") or item.get("symbolName")
                            if sym:
                                symbols_set.add(sym.strip().upper())
        except Exception as e:
            logger.warning(f"NSE 52W High API fetch failed: {e}")

        # If live API succeeded, keep those candidates (clean and fast).
        # Only fall back to local quality universe if live API completely failed to find symbols.
        if not symbols_set:
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                        if cached:
                            return cached
                except Exception as e:
                    logger.warning(f"Failed fallback cache read: {e}")

            quality_symbols = self.load_quality_universe_symbols()
            for q_sym in quality_symbols:
                symbols_set.add(q_sym.strip().upper())

        # Filter out obvious non-equity symbols
        filtered = [s for s in symbols_set if not s.endswith("-RE") and not s.startswith("DUMMY")]
        sorted_symbols = sorted(filtered)
        if sorted_symbols:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(sorted_symbols, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write 52W high cache: {e}")

        return sorted_symbols

    # -------------------------------------------------------------------------
    # STEP 2: TECHNICAL LEVELS, BASE STRUCTURE & EXHAUSTION
    # -------------------------------------------------------------------------

    @staticmethod
    def calculate_technical_levels(df: pd.DataFrame) -> Dict[str, float]:
        """Compute rolling 52W high, volume SMAs, EMAs, and ATR for 52W High breakouts.
        
        Requires a DataFrame with 'open', 'high', 'low', 'close', 'volume'.
        """
        if df.empty or len(df) < 20:
            raise ValueError(f"Insufficient candle history ({len(df)} bars, need >= 20)")

        d = df.copy()
        d.columns = [str(c).lower() for c in d.columns]

        # Prior 252-day high (excluding today's bar to test if today is breaking out)
        roll_window = min(252, len(d))
        prior_high_series = d["high"].shift(1).rolling(window=roll_window - 1, min_periods=20).max()
        prior_52w_high = float(prior_high_series.iloc[-1]) if pd.notna(prior_high_series.iloc[-1]) else float(d["high"].max())

        # Rolling high including today
        high_52w = float(d["high"].rolling(window=roll_window, min_periods=20).max().iloc[-1])

        # 20-day Volume SMA (calculated on shift(1) prior sessions)
        vol_sma20_series = d["volume"].shift(1).rolling(window=20, min_periods=5).mean()
        vol_sma20 = float(vol_sma20_series.iloc[-1])
        vol_today = float(d["volume"].iloc[-1])
        vol_ratio = round(vol_today / vol_sma20, 2) if vol_sma20 > 0 else 1.0

        # Multi-session lookback (last 5 trading days)
        vol_ratios_series = (d["volume"] / vol_sma20_series.replace(0, float("nan"))).fillna(1.0)
        recent_window = min(5, len(d))
        max_vol_ratio_5d = round(float(vol_ratios_series.iloc[-recent_window:].max()), 2)
        max_high_5d = float(d["high"].iloc[-recent_window:].max())

        # Moving Averages
        ema5 = float(d["close"].ewm(span=5, adjust=False).mean().iloc[-1])
        ema20 = float(d["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(d["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        sma150 = float(d["close"].rolling(window=min(150, len(d)), min_periods=20).mean().iloc[-1])

        sma200_series = d["close"].rolling(window=min(200, len(d)), min_periods=20).mean()
        sma200 = float(sma200_series.iloc[-1])
        sma200_20d_ago = float(sma200_series.iloc[-min(21, len(sma200_series))])

        # ATR 14
        tr1 = d["high"] - d["low"]
        tr2 = (d["high"] - d["close"].shift(1)).abs()
        tr3 = (d["low"] - d["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14_series = tr.rolling(window=14, min_periods=5).mean()
        atr14 = float(atr14_series.iloc[-1])

        last_bar = d.iloc[-1]

        return {
            "prior_52w_high": prior_52w_high,
            "high_52w": high_52w,
            "vol_sma20": vol_sma20,
            "today_volume": int(vol_today),
            "volume_ratio": vol_ratio,
            "max_vol_ratio_5d": max_vol_ratio_5d,
            "max_high_5d": max_high_5d,
            "today_open": float(last_bar["open"]),
            "today_high": float(last_bar["high"]),
            "today_low": float(last_bar["low"]),
            "today_close": float(last_bar["close"]),
            "ema5": round(ema5, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "sma150": round(sma150, 2),
            "sma200": round(sma200, 2),
            "sma200_20d_ago": round(sma200_20d_ago, 2),
            "atr14": round(atr14, 2),
        }

    @staticmethod
    def detect_consolidation_base(
        df: pd.DataFrame,
        base_window: int = 50,
        min_base_days: int = 15,
        max_depth_pct: float = MAX_BASE_DEPTH_PCT,
        max_atr_ratio: float = MAX_ATR_CONTRACTION_RATIO,
    ) -> ConsolidationBaseMetrics:
        """Evaluate whether the stock consolidated in a valid base/VCP prior to breakout.
        
        Rules:
        1. Base Duration: 15 to 60 trading days
        2. Base Depth: Max drawdown from prior high within base <= 20%
        3. ATR Contraction: ATR at breakout <= 80% of ATR at start of base
        4. Weinstein Stage 2: Price > 150 SMA, Price > 200 SMA, and 200 SMA is rising
        """
        d = df.copy()
        d.columns = [str(c).lower() for c in d.columns]
        failures: List[str] = []

        if len(d) < min_base_days:
            failures.append(f"Insufficient history ({len(d)} bars, need >= {min_base_days})")
            return ConsolidationBaseMetrics(
                base_duration_days=len(d),
                base_depth_pct=999.0,
                atr_contraction_ratio=999.0,
                above_150_sma=False,
                above_200_sma=False,
                rising_200_sma=False,
                passed_base_check=False,
                failure_reasons=failures,
            )

        # Slice base slice (prior 15-60 sessions excluding today's breakout)
        slice_len = min(base_window, len(d) - 1)
        base_slice = d.iloc[-(slice_len + 1): -1] if slice_len > 0 else d.iloc[:-1]

        if base_slice.empty:
            base_slice = d.iloc[:-1]

        base_duration = len(base_slice)
        prior_high = float(base_slice["high"].max())
        lowest_low = float(base_slice["low"].min())

        base_depth_pct = round(((prior_high - lowest_low) / prior_high) * 100, 2) if prior_high > 0 else 0.0

        if base_depth_pct > max_depth_pct:
            failures.append(f"Base depth of {base_depth_pct:.1f}% exceeds max {max_depth_pct:.1f}%")

        # ATR Contraction (VCP check)
        # Measures volatility contraction inside the consolidation base leading up to the breakout:
        # Compares pre-breakout ATR (just before breakout bar) against peak ATR established during early base
        tr1 = d["high"] - d["low"]
        tr2 = (d["high"] - d["close"].shift(1)).abs()
        tr3 = (d["low"] - d["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=14, min_periods=5).mean()

        base_atr_slice = atr_series.iloc[-(slice_len + 1): -1]
        recent_pre_breakout_atr = float(atr_series.iloc[-2]) if len(atr_series) >= 2 else float(atr_series.iloc[-1])
        peak_base_atr = float(base_atr_slice.max()) if not base_atr_slice.empty and pd.notna(base_atr_slice.max()) else recent_pre_breakout_atr

        atr_ratio = round(recent_pre_breakout_atr / peak_base_atr, 2) if peak_base_atr > 0 else 1.0

        if atr_ratio > max_atr_ratio:
            failures.append(f"ATR contraction ratio {atr_ratio:.2f} exceeds {max_atr_ratio:.2f}")

        # Moving Averages
        close_today = float(d["close"].iloc[-1])
        sma150 = float(d["close"].rolling(min(150, len(d)), min_periods=20).mean().iloc[-1])
        sma200_series = d["close"].rolling(min(200, len(d)), min_periods=20).mean()
        sma200 = float(sma200_series.iloc[-1])
        sma200_prev = float(sma200_series.iloc[-min(21, len(sma200_series))])

        above_150 = close_today > sma150
        above_200 = close_today > sma200
        rising_200 = sma200 >= (sma200_prev * 0.998)  # Flat or strictly rising

        if not above_150:
            failures.append(f"Price (₹{close_today:.1f}) is below 150 SMA (₹{sma150:.1f})")
        if not above_200:
            failures.append(f"Price (₹{close_today:.1f}) is below 200 SMA (₹{sma200:.1f})")
        if not rising_200:
            failures.append("200-day SMA is sloping downward")

        passed = len(failures) == 0
        return ConsolidationBaseMetrics(
            base_duration_days=base_duration,
            base_depth_pct=base_depth_pct,
            atr_contraction_ratio=atr_ratio,
            above_150_sma=above_150,
            above_200_sma=above_200,
            rising_200_sma=rising_200,
            passed_base_check=passed,
            failure_reasons=failures,
        )

    @staticmethod
    def detect_exhaustion_climax(
        df: pd.DataFrame,
        tech: Optional[Dict[str, float]] = None,
    ) -> ExhaustionMetrics:
        """Check if today's candle exhibits buying climax / exhaustion distribution signals.
        
        Triggers:
        1. Parabolic run: Price > 40% above 50 EMA
        2. Severe upper wick: Upper shadow >= 50% of candle range
        3. Weak close: Close in lower 40% of candle range
        4. Extreme churn: Volume > 15x 20d SMA with < 1% price gain
        """
        d = df.copy()
        d.columns = [str(c).lower() for c in d.columns]
        last_bar = d.iloc[-1]

        high = float(last_bar["high"])
        low = float(last_bar["low"])
        close = float(last_bar["close"])
        candle_range = high - low

        ema50 = tech["ema50"] if tech else float(d["close"].ewm(span=50, adjust=False).mean().iloc[-1])
        vol_today = float(last_bar["volume"])
        vol_sma20 = tech["vol_sma20"] if tech else float(d["volume"].shift(1).rolling(20, min_periods=5).mean().iloc[-1])

        # 1. Parabolic Run
        is_parabolic = (close > (ema50 * 1.40)) if ema50 > 0 else False

        # 2. Upper Rejection Wick
        upper_wick = high - max(close, float(last_bar["open"]))
        has_rejection_wick = (upper_wick >= (0.50 * candle_range)) if candle_range > 0 else False

        # 3. Close in Lower 40%
        close_pos = (close - low) / candle_range if candle_range > 0 else 0.50
        close_in_lower_half = close_pos < 0.40

        # 4. Extreme Churn Volume (> 15x with < 1% gain)
        prev_close = float(d["close"].iloc[-2]) if len(d) >= 2 else close
        pct_gain = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
        vol_mult = (vol_today / vol_sma20) if vol_sma20 > 0 else 1.0
        extreme_volume = (vol_mult > 15.0) and (pct_gain < 1.0)

        score = sum([is_parabolic, has_rejection_wick, close_in_lower_half, extreme_volume])
        is_exhausted = score >= 2

        return ExhaustionMetrics(
            is_parabolic=is_parabolic,
            has_rejection_wick=has_rejection_wick,
            close_in_lower_half=close_in_lower_half,
            extreme_volume=extreme_volume,
            exhaustion_score=score,
            is_exhausted=is_exhausted,
        )

    # -------------------------------------------------------------------------
    # STEP 3: CANDIDATE SCANNER (STAGE 1 RADAR)
    # -------------------------------------------------------------------------

    def scan_candidate(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
    ) -> Optional[BreakoutSignal]:
        """Scan a candidate symbol to evaluate if it qualifies for a 52W High Breakout Signal.
        
        Args:
            symbol: Ticker symbol (e.g., 'TRENT', 'HAL', 'BEL').
            df: Optional pre-loaded daily DataFrame (OHLCV). If None, uses cache_manager.
            as_of_date: Optional date string 'YYYY-MM-DD' for backtesting.
            skip_fundamental_audit: If True, bypasses ScreenerClient.
            
        Returns:
            BreakoutSignal if all 4 layers pass and exhaustion guard is clear, else None.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")

        # 1. Fetch Daily Candles
        if df is None:
            if self.cache_manager is None:
                raise ValueError("No DataFrame provided and no cache_manager configured.")
            end_d = as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            start_d = (pd.to_datetime(end_d) - pd.Timedelta(days=500)).strftime("%Y-%m-%d")
            df = self.cache_manager.get_candles(
                symbol=clean_sym,
                exchange="NSE",
                interval="1d",
                start_date=start_d,
                end_date=end_d,
            )

        if df is None or len(df) < 20:
            return None

        # Slice to as_of_date if specified
        if as_of_date:
            as_of_ts = pd.to_datetime(as_of_date)
            if df.index.tz is not None and as_of_ts.tz is None:
                as_of_ts = as_of_ts.tz_localize(df.index.tz)
            df = df.loc[df.index <= as_of_ts]
            if df.empty or len(df) < 20:
                return None

        # 2. Technical Metrics
        try:
            tech = self.calculate_technical_levels(df)
        except ValueError as e:
            logger.debug(f"Insufficient history for {clean_sym}: {e}")
            return None

        # 3. Layer 1 Check: 52-Week High Proximity (within BREAKOUT_PROXIMITY_TOLERANCE)
        today_high = tech["today_high"]
        today_close = tech["today_close"]
        high_52w = tech["high_52w"]
        prior_52w_high = tech["prior_52w_high"]
        max_high_5d = tech.get("max_high_5d", today_high)

        # Passes if today's close is within 3% of 52W high, or today's high broke prior 52W high,
        # or printed a fresh 52W high in the last 5 days and is holding within 3% of it
        is_52w_high = (
            (today_close >= (high_52w * (1.0 - BREAKOUT_PROXIMITY_TOLERANCE)))
            or (today_high >= (prior_52w_high * 0.995))
            or (max_high_5d >= (high_52w * 0.995) and today_close >= (max_high_5d * (1.0 - BREAKOUT_PROXIMITY_TOLERANCE)))
        )

        if not is_52w_high:
            return None

        # 4. Layer 2 Check: Consolidation Base / VCP Check
        base_metrics = self.detect_consolidation_base(df)
        if not base_metrics.passed_base_check:
            logger.debug(f"{clean_sym} failed base check: {base_metrics.failure_reasons}")
            return None

        # 5. Layer 3 Check: Institutional Volume Anomaly (>= 2.0x 20d SMA, <= 20x)
        vol_ratio = tech["volume_ratio"]
        max_vol_ratio_5d = tech.get("max_vol_ratio_5d", vol_ratio)

        has_volume = (vol_ratio >= VOLUME_ANOMALY_FACTOR) or (max_vol_ratio_5d >= 2.5)
        if not has_volume or vol_ratio > MAX_VOLUME_CEILING:
            return None

        # 6. Negative Filter: Exhaustion Climax Guard
        exhaustion = self.detect_exhaustion_climax(df, tech=tech)
        if exhaustion.is_exhausted:
            logger.info(f"{clean_sym} rejected by Exhaustion Guard: score={exhaustion.exhaustion_score}")
            return None

        # 7. Layer 4 Check: Growth Fundamental Screen
        audit = None
        if not skip_fundamental_audit:
            try:
                audit = self.screener.audit_growth_company(clean_sym)
                if not audit.passed_audit:
                    logger.info(f"{clean_sym} rejected by growth audit: {audit.failure_reasons}")
                    return None
            except Exception as e:
                logger.warning(f"Could not audit {clean_sym}: {e}")
                return None
        else:
            audit = FundamentalAudit(
                symbol=clean_sym,
                audit_date=as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                passed_audit=True,
            )

        # 8. Insider Buying check (Conviction Amplifier)
        insider_trade = self.insider.get_symbol_insider_activity(clean_sym)

        # 9. Automated Levels & Targets
        candle_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])[:10]
        breakout_px = today_close
        today_low = tech["today_low"]
        breakout_low = today_low

        # Initial SL: Low of breakout candle or close - 6% (whichever is tighter)
        initial_sl = max(breakout_low, breakout_px * (1.0 - MAX_INITIAL_SL_PCT))
        trailing_20ema = tech["ema20"]
        target_1 = round(breakout_px * (1.0 + TARGET_1_PCT), 2)
        target_2 = round(breakout_px * (1.0 + TARGET_2_PCT), 2)

        return BreakoutSignal(
            symbol=clean_sym,
            breakout_date=candle_date,
            breakout_price=breakout_px,
            high_52w=high_52w,
            today_high=today_high,
            today_low=today_low,
            today_volume=tech["today_volume"],
            avg_volume_20d=tech["vol_sma20"],
            volume_ratio=max(vol_ratio, max_vol_ratio_5d),
            initial_sl=round(initial_sl, 2),
            trailing_20ema=trailing_20ema,
            target_1_15pct=target_1,
            target_2_30pct=target_2,
            base_metrics=base_metrics,
            exhaustion=exhaustion,
            audit=audit,
            insider_activity=insider_trade,
            stage=BreakoutStage.RADAR,
        )

    # -------------------------------------------------------------------------
    # FUNNEL SCANNER (FULL END-TO-END PIPELINE)
    # -------------------------------------------------------------------------

    def run_funnel_scan(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
    ) -> List[BreakoutSignal]:
        """Execute the full 4-layer breakout funnel across candidate symbols.
        
        If candidate_symbols is omitted, automatically fetches today's 52W-high list.
        """
        if candidate_symbols is None:
            candidate_symbols = self.fetch_nse_52w_high_symbols()

        signals: List[BreakoutSignal] = []
        logger.info(f"Starting 52W-high funnel scan across {len(candidate_symbols)} candidate symbols...")

        for sym in candidate_symbols:
            try:
                sig = self.scan_candidate(
                    symbol=sym,
                    as_of_date=as_of_date,
                    skip_fundamental_audit=skip_fundamental_audit,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                logger.warning(f"Error scanning candidate {sym}: {e}")

        # Sort signals by volume expansion descending (highest institutional power first)
        signals.sort(key=lambda s: s.volume_ratio, reverse=True)
        return signals

    # -------------------------------------------------------------------------
    # STEP 4: STAGE 2 BUY CONFIRMATION STATE MACHINE
    # -------------------------------------------------------------------------

    @staticmethod
    def evaluate_stage2_confirmation(
        pivot_high: float,
        initial_sl: float,
        follow_through_bar: pd.Series,
    ) -> Tuple[BreakoutStage, Optional[float]]:
        """Evaluate follow-through daily candle (T+1 to T+5) against breakout pivots.
        
        Rules:
        - INVALIDATED: follow_through close < initial_sl OR close > 5% below pivot_high
        - CONFIRMED_BUY: follow_through close > pivot_high
        - RADAR: Holding support between initial_sl and pivot_high, awaiting follow-through
        """
        bar_close = float(follow_through_bar["close"])

        # Invalidation check: broke below initial SL or collapsed > 5% below pivot high
        if bar_close < initial_sl or bar_close < (pivot_high * 0.95):
            return BreakoutStage.INVALIDATED, bar_close

        # Reversal Confirmation: Closed cleanly above breakout pivot high
        if bar_close > pivot_high:
            return BreakoutStage.CONFIRMED_BUY, bar_close

        return BreakoutStage.RADAR, None

    def check_watchlist(
        self,
        watchlist: List[HighWatchlistStock],
        get_daily_bars_fn: Any,
    ) -> List[HighWatchlistStock]:
        """Check active 52W High Watchlist stocks for Stage 2 Buy triggers."""
        updated: List[HighWatchlistStock] = []

        for stock in watchlist:
            if stock.is_buy_triggered:
                updated.append(stock)
                continue

            try:
                df = get_daily_bars_fn(stock.symbol)
                if df is None or df.empty:
                    updated.append(stock)
                    continue

                latest_dt = (
                    df.index[-1].strftime("%Y-%m-%d")
                    if hasattr(df.index[-1], "strftime")
                    else str(df.index[-1])[:10]
                )
                if stock.breakout_date and latest_dt <= stock.breakout_date:
                    updated.append(stock)
                    continue

                latest_bar = df.iloc[-1]
                stage, trigger_px = self.evaluate_stage2_confirmation(
                    pivot_high=stock.pivot_high,
                    initial_sl=stock.initial_sl,
                    follow_through_bar=latest_bar,
                )

                if stage == BreakoutStage.CONFIRMED_BUY:
                    stock.is_buy_triggered = True
                    stock.trigger_date = latest_dt
                    stock.trigger_price = trigger_px
                    stock.add_note(
                        f"Stage 2 BUY CONFIRMED on {latest_dt} @ ₹{trigger_px:.2f} "
                        f"(Pivot High: ₹{stock.pivot_high:.2f}, SL: ₹{stock.initial_sl:.2f})."
                    )
                elif stage == BreakoutStage.INVALIDATED:
                    marker = f"Breakout invalidated on {latest_dt}"
                    if not any(marker in n for n in stock.history_notes):
                        stock.add_note(
                            f"{marker}: closed @ ₹{trigger_px:.2f} below support/pivot threshold."
                        )
            except Exception as e:
                logger.warning(f"Error checking 52W high watchlist for {stock.symbol}: {e}")

            updated.append(stock)

        return updated
