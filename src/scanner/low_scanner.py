"""52-Week Low Technical Engine & State Machine.

Implements the 3-Step Institutional Funnel:
1. Broad 52W-Low Discovery (via NSE 52W-low report / candidate list)
2. Fundamental Solvency & Insider Filter (5 Golden Rules via ScreenerClient & InsiderFeed)
3. Targeted Technical Analysis & Level Calculation (Volume Anomaly, SL, 20 EMA, 50 EMA)
4. Stage 2 Confirmation State Machine (T+1/T+2 Follow-Through for Watchlist stocks)
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
import requests

from src.scanner.models import (
    CapitulationSignal,
    FundamentalAudit,
    InsiderTradeRecord,
    SignalStage,
    WatchlistStock,
)
from src.scanner.screener_client import ScreenerClient
from src.scanner.insider_feed import InsiderFeed

logger = logging.getLogger(__name__)

# Constants for discovery, caching, and technical rules
NSE_CACHE_TTL: int = 7200  # 2 hours in seconds
CAPITULATION_TOLERANCE: float = 0.005  # 0.5% tolerance near 52W low
VOLUME_ANOMALY_FACTOR: float = 3.0  # 3.0x 20-day SMA volume surge

_RANDOM_UAS: List[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class LowCapitulationScanner:
    """Technical scanner and two-stage state machine for 52-Week Low Capitulation Strategy."""

    NSE_52W_LOW_URL = "https://www.nseindia.com/api/live-analysis-variations?index=low"
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
    # STEP 1: BROAD 52W-LOW DISCOVERY
    # -------------------------------------------------------------------------

    def load_quality_universe_symbols(self) -> List[str]:
        """Load symbols from local quality universes (Nifty 500 / Nifty 200).
        
        Ensures high-conviction institutional compounders (e.g. AIAENG, NESTLEIND)
        are never missed even if external scraper endpoints fail or omit them.
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
                            sym = (row.get("Symbol") or "").strip().upper()
                            if sym and sym not in symbols:
                                symbols.append(sym)
                except Exception as e:
                    logger.warning(f"Error reading {cfg_path}: {e}")
        return symbols

    def fetch_nse_52w_low_symbols(self, force_refresh: bool = False) -> List[str]:
        """Fetch list of symbols currently at or near 52-week low directly from NSE.
        
        Cached locally for NSE_CACHE_TTL seconds to avoid hammering NSE endpoints.
        Combines NSE live API output with local quality universe (Nifty 500)
        to prevent missing institutional stocks that drift into 52W lows without
        being top daily percentage losers.
        """
        cache_file = self.cache_dir / "nse_52w_low_symbols.json"
        now = time.time()

        if not force_refresh and cache_file.exists():
            try:
                mtime = os.path.getmtime(cache_file)
                if (now - mtime) < NSE_CACHE_TTL:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)
                        if isinstance(cached_data, list):
                            return cached_data
            except Exception as e:
                logger.warning(f"Failed to read 52W low cache: {e}")

        symbols_set: set[str] = set()
        ua = random.choice(_RANDOM_UAS) if _RANDOM_UAS else self.DEFAULT_USER_AGENT

        try:
            s = requests.Session()
            s.headers.update(
                {
                    "User-Agent": ua,
                    "Accept": "*/*",
                    "Referer": "https://www.nseindia.com/market-data/52-week-high-low",
                }
            )
            # Hit homepage first to collect cookies
            try:
                s.get("https://www.nseindia.com", timeout=6)
            except Exception:
                pass

            resp = s.get(self.NSE_52W_LOW_URL, timeout=10)
            if resp.status_code in (404, 429):
                logger.warning(f"NSE 52W Low API returned {resp.status_code}; falling back immediately to cache.")
                if cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception as e:
                        logger.warning(f"Error reading cache on {resp.status_code} fallback: {e}")
            elif resp.status_code == 200:
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
            else:
                logger.warning(f"NSE 52W Low API status: {resp.status_code}")

            # If empty, fallback to live analysis losers near 52-week low
            if not symbols_set:
                r_loosers = s.get("https://www.nseindia.com/api/live-analysis-variations?index=loosers", timeout=10)
                if r_loosers.status_code in (404, 429) and cache_file.exists():
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except Exception:
                        pass
                elif r_loosers.status_code == 200:
                    d_loosers = r_loosers.json()
                    if isinstance(d_loosers, dict):
                        for sec in ["allSec", "FOSec", "NIFTY", "NIFTYNEXT50"]:
                            sec_data = d_loosers.get(sec, {})
                            if isinstance(sec_data, dict):
                                for it in sec_data.get("data", []):
                                    if isinstance(it, dict):
                                        sym = it.get("symbol")
                                        near_wkl = it.get("nearWKL", -999)
                                        # Within 15% of 52W low
                                        if sym and near_wkl > -15.0:
                                            symbols_set.add(sym.strip().upper())
        except Exception as e:
            logger.warning(f"NSE 52W Low API fetch failed: {e}")

        # Fallback / Supplement with local Quality Universe (Nifty 500)
        quality_symbols = self.load_quality_universe_symbols()
        for q_sym in quality_symbols:
            symbols_set.add(q_sym.strip().upper())

        # Fallback to cached data if exists and still empty
        if not symbols_set and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed fallback cache read: {e}")

        sorted_symbols = sorted(symbols_set)
        if sorted_symbols:
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(sorted_symbols, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write 52W low cache: {e}")

        return sorted_symbols

    # -------------------------------------------------------------------------
    # STEP 2 & 3: TECHNICAL COMPUTATION & LEVEL CALCULATION
    # -------------------------------------------------------------------------

    @staticmethod
    def calculate_technical_levels(df: pd.DataFrame) -> Dict[str, float]:
        """Compute rolling 52W low, 20-day volume SMA, EMAs, and capitulation levels.
        
        Requires a DataFrame with 'open', 'high', 'low', 'close', 'volume'.

        Raises:
            ValueError: If df is empty or contains fewer than 20 daily bars required
                to compute the 20-day volume baseline and moving averages.
        """
        if df.empty or len(df) < 20:
            raise ValueError(f"Insufficient candle history ({len(df)} bars, need >= 20)")

        # Work on a copy with lowercase columns
        d = df.copy()
        d.columns = [str(c).lower() for c in d.columns]

        # Rolling 252-day low (min_periods=20 for younger listings)
        roll_window = min(252, len(d))
        low_52w = d["low"].rolling(window=roll_window, min_periods=20).min().iloc[-1]

        # 20-day Volume SMA (calculated on PRIOR 20 trading sessions to prevent today's anomaly from skewing the baseline)
        vol_sma20_series = d["volume"].shift(1).rolling(window=20, min_periods=5).mean()
        vol_sma20 = vol_sma20_series.iloc[-1]
        vol_today = float(d["volume"].iloc[-1])
        vol_ratio = round(vol_today / vol_sma20, 2) if vol_sma20 > 0 else 1.0

        # Rolling 5-day max volume anomaly (to detect multi-day capitulation / secondary tests)
        vol_ratios_series = (d["volume"] / vol_sma20_series.replace(0, float("nan"))).fillna(1.0)
        recent_window = min(5, len(d))
        max_vol_ratio_5d = round(float(vol_ratios_series.iloc[-recent_window:].max()), 2)
        min_low_5d = float(d["low"].iloc[-recent_window:].min())

        # EMAs (Wilder/Standard exponential)
        ema5 = float(d["close"].ewm(span=5, adjust=False).mean().iloc[-1])
        ema20 = float(d["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(d["close"].ewm(span=50, adjust=False).mean().iloc[-1])

        last_bar = d.iloc[-1]

        return {
            "low_52w": float(low_52w),
            "vol_sma20": float(vol_sma20),
            "today_volume": int(vol_today),
            "volume_ratio": float(vol_ratio),
            "max_vol_ratio_5d": float(max_vol_ratio_5d),
            "min_low_5d": float(min_low_5d),
            "today_open": float(last_bar["open"]),
            "today_high": float(last_bar["high"]),
            "today_low": float(last_bar["low"]),
            "today_close": float(last_bar["close"]),
            "ema5": round(ema5, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
        }

    # -------------------------------------------------------------------------
    # STEP 3: CANDIDATE SCANNER (STAGE 1 RADAR)
    # -------------------------------------------------------------------------

    def scan_candidate(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
    ) -> Optional[CapitulationSignal]:
        """Scan a candidate symbol to determine if it produces a Stage 1 Capitulation Signal.
        
        Args:
            symbol: Stock ticker (e.g., 'NESTLEIND' or 'TATACONSUM')
            df: Optional pre-loaded daily DataFrame (OHLCV). If None, uses cache_manager.
            as_of_date: Optional date string 'YYYY-MM-DD' for backtesting.
            skip_fundamental_audit: If True, bypasses ScreenerClient (used in offline tests).
            
        Returns:
            CapitulationSignal if all criteria pass, else None.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")

        # 1. Targeted Historical Candles
        if df is None:
            if self.cache_manager is None:
                raise ValueError("No DataFrame provided and no cache_manager configured.")
            # Fetch daily candles
            end_d = as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            # Fetch at least 1.5 years back to ensure clean 252-day rolling window
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
            logger.debug("Insufficient history for %s: %s", clean_sym, e)
            return None

        # 3. Technical Rule 1: Fresh 52-Week Low (within CAPITULATION_TOLERANCE)
        today_low = tech["today_low"]
        low_52w = tech["low_52w"]
        min_low_5d = tech.get("min_low_5d", today_low)
        # Holds if today's low is at 52W low, or if 52W low was printed in last 5 days and today is testing within tolerance
        is_52w_low = (today_low <= (low_52w * (1.0 + CAPITULATION_TOLERANCE))) or (
            min_low_5d <= (low_52w * (1.0 + CAPITULATION_TOLERANCE))
            and today_low <= (min_low_5d * (1.0 + 3 * CAPITULATION_TOLERANCE))
        )

        if not is_52w_low:
            return None

        # 4. Technical Rule 2: Institutional Volume Anomaly (>= VOLUME_ANOMALY_FACTOR x 20-day SMA)
        # Accepts either today's anomaly OR a primary climax (>= VOLUME_ANOMALY_FACTOR) within the last 5 trading days
        vol_ratio = tech["volume_ratio"]
        max_vol_ratio_5d = tech.get("max_vol_ratio_5d", vol_ratio)

        if vol_ratio < VOLUME_ANOMALY_FACTOR and max_vol_ratio_5d < VOLUME_ANOMALY_FACTOR:
            return None

        # Effective volume anomaly for display
        effective_vol_ratio = max(vol_ratio, max_vol_ratio_5d)
        effective_low = min(today_low, min_low_5d)

        # 5. Fundamental Audit (Funnel Step 2 - only executed if technical conditions pass)
        audit = None
        if not skip_fundamental_audit:
            try:
                audit = self.screener.audit_company(clean_sym)
                if not audit.passed_audit:
                    logger.info(f"{clean_sym} rejected by fundamental audit: {audit.failure_reasons}")
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

        # 6. Check for Insider Buying kicker
        insider_trade = self.insider.get_symbol_insider_activity(clean_sym)

        # 7. Automated Levels
        candle_date = df.index[-1].strftime("%Y-%m-%d") if hasattr(df.index[-1], "strftime") else str(df.index[-1])[:10]

        return CapitulationSignal(
            symbol=clean_sym,
            capitulation_date=candle_date,
            low_price=effective_low,
            high_price=tech["today_high"],
            close_price=tech["today_close"],
            today_volume=tech["today_volume"],
            avg_volume_20d=tech["vol_sma20"],
            volume_ratio=effective_vol_ratio,
            support_sl=effective_low,        # Soft Stop-Loss baseline
            target_1_20ema=tech["ema20"],    # Target 1
            target_2_50ema=tech["ema50"],    # Target 2
            audit=audit,
            insider_activity=insider_trade,
            stage=SignalStage.RADAR,
        )

    # -------------------------------------------------------------------------
    # FUNNEL SCANNER (FULL END-TO-END PIPELINE)
    # -------------------------------------------------------------------------

    def run_funnel_scan(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
    ) -> List[CapitulationSignal]:
        """Execute the full 3-step funnel across candidate symbols.
        
        If candidate_symbols is omitted, automatically fetches today's 52W-low list from NSE.
        """
        if candidate_symbols is None:
            candidate_symbols = self.fetch_nse_52w_low_symbols()

        signals: List[CapitulationSignal] = []
        logger.info(f"Starting 52W-low funnel scan across {len(candidate_symbols)} candidate symbols...")

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

        # Sort signals by volume anomaly descending (highest institutional absorption first)
        signals.sort(key=lambda s: s.volume_ratio, reverse=True)
        return signals

    # -------------------------------------------------------------------------
    # STEP 4: STAGE 2 BUY CONFIRMATION STATE MACHINE
    # -------------------------------------------------------------------------

    @staticmethod
    def evaluate_stage2_confirmation(
        capitulation_low: float,
        capitulation_high: float,
        follow_through_bar: pd.Series,
        ema5: Optional[float] = None,
    ) -> Tuple[SignalStage, Optional[float]]:
        """Evaluate a follow-through daily candle (T+1, T+2, ...) against confirmation pivots.
        
        Rules:
        - INVALIDATED: follow_through close < capitulation_low (support violated)
        - CONFIRMED_BUY: follow_through close > capitulation_high OR follow_through close > ema5
        - RADAR: Still consolidating within range above capitulation_low

        Args:
            capitulation_low: Capitulation bar low serving as the soft stop-loss baseline.
            capitulation_high: Capitulation bar high serving as the primary breakout pivot.
            follow_through_bar: pd.Series representing the follow-through daily OHLCV bar.
            ema5: Optional float representing the 5-day Exponential Moving Average (EMA5),
                used as an alternative dynamic 'break-through' reversal trigger for Stage 2
                confirmation when price reclaims the 5 EMA even before clearing the
                capitulation candle's absolute high.
        
        Returns:
            Tuple of (SignalStage, confirmation_price or None)
        """
        bar_close = float(follow_through_bar["close"])
        bar_low = float(follow_through_bar["low"])

        # Invalidation check: EOD close broke capitulation low
        if bar_close < capitulation_low:
            return SignalStage.INVALIDATED, bar_close

        # Reversal Confirmation: Closed above capitulation candle high or reclaimed 5 EMA
        is_above_high = bar_close > capitulation_high
        is_above_ema5 = (ema5 is not None) and (bar_close > ema5)

        if is_above_high or is_above_ema5:
            return SignalStage.CONFIRMED_BUY, bar_close

        # Otherwise holding support but awaiting breakout
        return SignalStage.RADAR, None

    def check_watchlist(
        self,
        watchlist: List[WatchlistStock],
        get_daily_bars_fn: Any,
    ) -> List[WatchlistStock]:
        """Check active Watchlist stocks for Stage 2 Buy triggers.
        
        Args:
            watchlist: List of WatchlistStock items to evaluate.
            get_daily_bars_fn: Callable `fn(symbol) -> pd.DataFrame` returning daily candles.
            
        Returns:
            Updated list of WatchlistStock items with trigger statuses populated.
        """
        updated: List[WatchlistStock] = []

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
                # Only evaluate follow-through bars strictly after capitulation_date
                if stock.capitulation_date and latest_dt <= stock.capitulation_date:
                    updated.append(stock)
                    continue

                # Get latest daily candle
                latest_bar = df.iloc[-1]
                ema5 = float(df["close"].ewm(span=5, adjust=False).mean().iloc[-1]) if len(df) >= 5 else None

                stage, trigger_px = self.evaluate_stage2_confirmation(
                    capitulation_low=stock.capitulation_low,
                    capitulation_high=stock.capitulation_high,
                    follow_through_bar=latest_bar,
                    ema5=ema5,
                )

                if stage == SignalStage.CONFIRMED_BUY:
                    stock.is_buy_triggered = True
                    stock.trigger_date = latest_dt
                    stock.trigger_price = trigger_px
                    stock.add_note(
                        f"Stage 2 BUY TRIGGERED on {latest_dt} @ ₹{trigger_px:.2f} "
                        f"(Pivot High: ₹{stock.capitulation_high:.2f}"
                        + (f", 5 EMA: ₹{ema5:.2f}" if ema5 is not None else "")
                        + ")."
                    )
                elif stage == SignalStage.INVALIDATED:
                    marker = f"Support invalidated on {latest_dt}"
                    if not any(marker in n for n in stock.history_notes):
                        stock.add_note(
                            f"{marker}: closed @ ₹{trigger_px:.2f} below capitulation low ₹{stock.capitulation_low:.2f}."
                        )

            except Exception as e:
                logger.warning(f"Error checking watchlist for {stock.symbol}: {e}")

            updated.append(stock)

        return updated
