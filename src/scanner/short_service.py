"""Unified Facade Service for 52-Week High Exhaustion Short Strategy (Phase 1).

Provides high-level methods for Day 1 Climax Discovery, Day 2 Breakdown Evaluation,
Watchlist/Ledger querying, and Markdown Briefing generation.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.scanner.models import (
    DailyDashboard52Short,
    ExhaustionShortSignal,
    ShortExitReason,
    ShortSignalStage,
    ShortTradeRecord,
    ShortWatchlistStock,
)
from src.scanner.short_scanner import HighExhaustionShortScanner
from src.scanner.short_tracker import ShortPortfolioTracker

logger = logging.getLogger(__name__)


class ShortScannerService:
    """Unified service facade for 52-Week High Exhaustion Short Strategy."""

    IST = timezone(timedelta(hours=5, minutes=30))

    def __init__(
        self,
        cache_dir: str = "data/cache",
        data_dir: str = "data",
        cache_manager: Optional[Any] = None,
        tz: Optional[timezone] = None,
    ):
        self.tz = tz or self.IST
        self.cache_dir = Path(cache_dir)
        self.data_dir = Path(data_dir)

        if cache_manager is None:
            try:
                from src.engine.smart_cache import SmartCacheManager
                self.cache_manager = SmartCacheManager(cache_dir=cache_dir, default_provider="yfinance")
            except Exception as e:
                logger.warning(f"Could not initialize default SmartCacheManager: {e}")
                self.cache_manager = None
        else:
            self.cache_manager = cache_manager

        self.tracker = ShortPortfolioTracker(data_dir=data_dir)
        self.scanner = HighExhaustionShortScanner(
            cache_manager=self.cache_manager,
            cache_dir=cache_dir,
        )

    @classmethod
    def _today_ist(cls, tz: Optional[timezone] = None) -> str:
        target_tz = tz or cls.IST
        return datetime.now(target_tz).date().isoformat()

    # -------------------------------------------------------------------------
    # DAILY BRIEFING PAYLOAD GENERATOR
    # -------------------------------------------------------------------------

    def get_daily_briefing(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        current_day2_dfs: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> DailyDashboard52Short:
        """Run daily scan for Day 1 Climax Traps & evaluate Day 2 Watchlist Breakdown Triggers."""
        dt_str = as_of_date or self._today_ist(self.tz)
        current_day2_dfs = current_day2_dfs or {}

        # 1. Discover Candidate Universe for Day 1 Climax Traps
        if candidate_symbols:
            discovery_symbols = [s.upper().replace(".NS", "").replace(".BO", "") for s in candidate_symbols]
        else:
            discovery_symbols = self.scanner.fetch_nse_52w_high_symbols()

        new_traps: List[ExhaustionShortSignal] = []
        for sym in discovery_symbols:
            try:
                sig = self.scanner.scan_candidate(sym, as_of_date=dt_str)
                if sig is not None:
                    new_traps.append(sig)
            except Exception as e:
                logger.warning(f"Error scanning {sym} for short climax: {e}")

        # 2. Evaluate Day 2 & Day 3 Breakdown Triggers on Existing Watchlist
        watchlist = self.tracker.get_watchlist()
        day2_triggers: List[ShortWatchlistStock] = []
        day3_triggers: List[ShortWatchlistStock] = []
        active_shorts: List[ShortWatchlistStock] = []

        for stock in watchlist:
            if stock.status in (ShortSignalStage.TRIGGERED_MIS, ShortSignalStage.TRIGGERED_DAY3_MIS):
                active_shorts.append(stock)
                continue

            day_df = current_day2_dfs.get(stock.symbol)
            if day_df is None and self.scanner.cache_manager is not None:
                try:
                    day_df = self.scanner.cache_manager.get_candles(
                        symbol=stock.symbol,
                        exchange="NSE",
                        interval="1d",
                        start_date=stock.climax_date,
                        end_date=dt_str,
                    )
                except Exception:
                    day_df = None

            if day_df is not None and not day_df.empty:
                stage, exec_px, note = self.scanner.evaluate_breakdown(stock, day_df)
                if stage == ShortSignalStage.TRIGGERED_MIS:
                    self.tracker.update_stock_status(stock.symbol, stage, note)
                    stock.status = stage
                    day2_triggers.append(stock)
                elif stage == ShortSignalStage.TRIGGERED_DAY3_MIS:
                    self.tracker.update_stock_status(stock.symbol, stage, note)
                    stock.status = stage
                    day3_triggers.append(stock)
                elif stage == ShortSignalStage.INVALIDATED:
                    self.tracker.update_stock_status(stock.symbol, stage, note)
                    self.tracker.remove_from_watchlist(stock.symbol)

        summary_notes = []
        if new_traps:
            summary_notes.append(f"Detected {len(new_traps)} Day 1 Climax Traps at 52W highs (Monitor for Day 2 breakdown).")
        else:
            summary_notes.append("No Day 1 Climax Traps detected today.")

        if day2_triggers:
            summary_notes.append(f"🔥 {len(day2_triggers)} Day 2 Intraday MIS Short triggers active today!")
        if day3_triggers:
            summary_notes.append(f"⚡ {len(day3_triggers)} Day 3 Continuation MIS Short triggers active today!")

        return DailyDashboard52Short(
            as_of_date=dt_str,
            new_climax_traps=new_traps,
            day2_mis_triggers=day2_triggers,
            day3_continuation_triggers=day3_triggers,
            active_intraday_shorts=active_shorts,
            summary_notes=summary_notes,
        )

    # -------------------------------------------------------------------------
    # MARKDOWN FORMATTER
    # -------------------------------------------------------------------------

    def format_daily_briefing_markdown(self, dashboard: DailyDashboard52Short) -> str:
        """Format the short strategy payload into an executive Markdown report."""
        lines = [
            f"# 🔻 52-Week High Exhaustion Short Briefing — {dashboard.as_of_date}",
            "",
            "> **Strategy**: Wyckoff UTAD Bull Trap -> Day 2 & Day 3 Intraday MIS Short (Exit before 3:10 PM)",
            "",
        ]

        # Section 1: Day 2 & Day 3 Action Triggers
        lines.append("### 🔥 1. Intraday MIS Short Triggers (Actionable Today)")
        all_triggers = dashboard.day2_mis_triggers + dashboard.day3_continuation_triggers
        if all_triggers:
            lines.append("| Symbol | Mode | Trigger Level | Hard Invalidation | Target 1 (-2%) | Target 2 (-4%) | Status |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for item in dashboard.day2_mis_triggers:
                lines.append(
                    f"| **{item.symbol}** | Day 2 Breakdown | ₹{item.trigger_level_low:.2f} (Day 1 Low) | "
                    f"₹{item.invalidation_level_high:.2f} | ₹{item.target_1_mis:.2f} | ₹{item.target_2_mis:.2f} | 🔴 **DAY 2 MIS** |"
                )
            for item in dashboard.day3_continuation_triggers:
                lines.append(
                    f"| **{item.symbol}** | Day 3 Continuation | ₹{item.trigger_level_low:.2f} (Day 2 Low) | "
                    f"₹{item.invalidation_level_high:.2f} | ₹{item.target_1_mis:.2f} | ₹{item.target_2_mis:.2f} | ⚡ **DAY 3 CONT** |"
                )
        else:
            lines.append("*No watchlist stocks triggered Day 2 or Day 3 Intraday MIS breakdown today.*")
        lines.append("")

        # Section 2: Day 1 Climax Traps (Tomorrow's Watchlist)
        lines.append("### 📡 2. Fresh Day 1 Climax Traps (Watch for Tomorrow Morning)")
        if dashboard.new_climax_traps:
            lines.append("| Symbol | 52W High | Day Low (Sell Trigger) | Vol Surge | Upper Wick | Parabolic 50 EMA | Action |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for sig in dashboard.new_climax_traps:
                lines.append(
                    f"| **{sig.symbol}** | ₹{sig.climax_high:.2f} | **₹{sig.climax_low:.2f}** | **{sig.volume_ratio:.2f}x** | "
                    f"{sig.upper_wick_pct:.1f}% | +{sig.parabolic_extension_pct:.1f}% | Short if breaks ₹{sig.climax_low:.2f} tomorrow |"
                )
            lines.append("")
            lines.append("💡 *To track any of these for tomorrow morning, tell copilot: `Add <SYMBOL> to 52 short watchlist`.*")
        else:
            lines.append("*No fresh Day 1 Climax Traps detected on the tape today.*")
        lines.append("")

        # Section 3: Active Shorts
        if dashboard.active_intraday_shorts:
            lines.append("### ⚡ 3. Active Intraday MIS Positions")
            lines.append("| Symbol | Short Trigger | Invalidation SL | Target 1 | Target 2 | Action |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for s in dashboard.active_intraday_shorts:
                mode_str = "Day 3 Cont" if s.is_continuation else "Day 2 MIS"
                lines.append(f"| **{s.symbol}** | ₹{s.trigger_level_low:.2f} ({mode_str}) | ₹{s.invalidation_level_high:.2f} | ₹{s.target_1_mis:.2f} | ₹{s.target_2_mis:.2f} | Active MIS |")
            lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # CONVENIENCE QUERY HELPERS
    # -------------------------------------------------------------------------

    def get_watchlist_summary(self) -> Tuple[List[ShortWatchlistStock], str]:
        """Return Day 1 short watchlist and formatted markdown table."""
        wl = self.tracker.get_watchlist()
        if not wl:
            return [], "*No stocks currently on 52-Week High Short Watchlist.*"

        lines = [
            "# 🔻 52-Week High Exhaustion Short Watchlist (Day 2 Pre-Triggers)",
            "| Symbol | Climax Date | Sell Trigger (Day 1 Low) | Hard Invalidation | Target 1 (-2%) | Target 2 (-4%) | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for s in wl:
            lines.append(
                f"| **{s.symbol}** | {s.climax_date} | **₹{s.trigger_level_low:.2f}** | ₹{s.invalidation_level_high:.2f} | "
                f"₹{s.target_1_mis:.2f} | ₹{s.target_2_mis:.2f} | {s.status.value} |"
            )
        return wl, "\n".join(lines)

    def scan_radar_candidates(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[ExhaustionShortSignal], str]:
        """Scan radar for Day 1 Climax Traps without modifying watchlist."""
        dt_str = as_of_date or self._today_ist(self.tz)
        if candidate_symbols:
            syms = [s.upper().replace(".NS", "").replace(".BO", "") for s in candidate_symbols]
        else:
            syms = self.scanner.fetch_nse_52w_high_symbols()

        traps: List[ExhaustionShortSignal] = []
        for sym in syms:
            try:
                sig = self.scanner.scan_candidate(sym, as_of_date=dt_str)
                if sig:
                    traps.append(sig)
            except Exception as e:
                logger.warning(f"Radar error {sym}: {e}")

        if not traps:
            return [], "*No stocks met the Day 1 Climax Upthrust criteria today.*"

        lines = [
            f"# 📡 52-Week High Exhaustion Radar ({dt_str})",
            "| Symbol | 52W High | Day Low (Sell Trigger) | Volume Ratio | Upper Wick | Extension vs 50 EMA | Action |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for s in traps:
            lines.append(
                f"| **{s.symbol}** | ₹{s.climax_high:.2f} | **₹{s.climax_low:.2f}** | **{s.volume_ratio:.2f}x** | "
                f"{s.upper_wick_pct:.1f}% | +{s.parabolic_extension_pct:.1f}% | Short on break below ₹{s.climax_low:.2f} |"
            )
        return traps, "\n".join(lines)
