"""Unified 52-Week Scanner Service — orchestrates High, Low & Short strategies.

This is the single entry point for:
    "whats today for 52" → Runs 52W High Breakout + 52W Low Capitulation + 52W High Exhaustion Shorts
                           and merges into a combined executive briefing.
    "52 watchlist"       → Renders 3 separate, dedicated strategy tables (Low, High, Short).
    "52 portfolio"       → Renders 2 separate tables: Long Positional Holdings vs Short Intraday MIS.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.scanner.high_service import HighScannerService
from src.scanner.service import ScannerService
from src.scanner.short_service import ShortScannerService

logger = logging.getLogger(__name__)


class UnifiedScannerService:
    """Orchestrates 52-Week Low, 52-Week High, and 52-Week Exhaustion Short strategies."""

    IST = timezone(timedelta(hours=5, minutes=30))

    def __init__(
        self,
        cache_dir: str = "data/cache",
        data_dir: str = "data",
        cache_manager: Optional[Any] = None,
        screener_client: Optional[Any] = None,
        insider_feed: Optional[Any] = None,
        tz: Optional[timezone] = None,
        # Allow injecting pre-built services for testing
        low_service: Optional[ScannerService] = None,
        high_service: Optional[HighScannerService] = None,
        short_service: Optional[ShortScannerService] = None,
    ):
        self.tz = tz or self.IST

        if low_service is not None:
            self.low = low_service
        else:
            self.low = ScannerService(
                cache_dir=cache_dir,
                data_dir=data_dir,
                cache_manager=cache_manager,
                screener_client=screener_client,
                insider_feed=insider_feed,
                tz=self.tz,
            )

        if high_service is not None:
            self.high = high_service
        else:
            self.high = HighScannerService(
                cache_dir=cache_dir,
                data_dir=data_dir,
                cache_manager=cache_manager,
                screener_client=screener_client,
                insider_feed=insider_feed,
                tz=self.tz,
            )

        if short_service is not None:
            self.short = short_service
        else:
            self.short = ShortScannerService(
                cache_dir=cache_dir,
                data_dir=data_dir,
                cache_manager=cache_manager,
                tz=self.tz,
            )

    @classmethod
    def _today_ist(cls, tz: Optional[timezone] = None) -> str:
        target_tz = tz or cls.IST
        return datetime.now(target_tz).date().isoformat()

    # -------------------------------------------------------------------------
    # UNIFIED DAILY BRIEFING
    # -------------------------------------------------------------------------

    def get_unified_daily_briefing(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        strategy: str = "all",  # "all", "both", "high", "low", "short"
        skip_fundamental_audit: bool = False,
    ) -> Dict[str, Any]:
        """Run strategies and return raw dashboard payloads."""
        dt_str = as_of_date or self._today_ist(self.tz)
        result: Dict[str, Any] = {
            "as_of_date": dt_str,
            "low_dashboard": None,
            "high_dashboard": None,
            "short_dashboard": None,
        }

        if strategy in ("all", "both", "low"):
            try:
                result["low_dashboard"] = self.low.get_daily_briefing(
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                    skip_fundamental_audit=skip_fundamental_audit,
                )
            except Exception as e:
                logger.warning(f"52W Low briefing error: {e}")
                result["low_error"] = str(e)

        if strategy in ("all", "both", "high"):
            try:
                result["high_dashboard"] = self.high.get_daily_briefing(
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                    skip_fundamental_audit=skip_fundamental_audit,
                )
            except Exception as e:
                logger.warning(f"52W High briefing error: {e}")
                result["high_error"] = str(e)

        if strategy in ("all", "short"):
            try:
                result["short_dashboard"] = self.short.get_daily_briefing(
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                )
            except Exception as e:
                logger.warning(f"52W Short briefing error: {e}")
                result["short_error"] = str(e)

        return result

    def format_unified_briefing_markdown(
        self,
        briefing: Dict[str, Any],
    ) -> str:
        """Merge all strategy dashboards into a single executive markdown briefing."""
        dt_str = briefing["as_of_date"]
        low_db = briefing.get("low_dashboard")
        high_db = briefing.get("high_dashboard")
        short_db = briefing.get("short_dashboard")

        md: List[str] = [
            f"# 📊 QuantCopilot: Unified 52-Week Briefing — {dt_str}",
            "",
            "> **Multi-Strategy**: 52W High Breakout + 52W Low Capitulation + 52W High Exhaustion Shorts (Intraday MIS)",
            "",
        ]

        # SECTION A: 52-WEEK HIGH BREAKOUT
        if high_db is not None:
            md.append("---")
            md.append("")
            md.append("## 🚀 A. 52-Week HIGH — Breakout Strategy (LONG)")
            md.append("")

            # Summary
            if high_db.summary_notes:
                md.append("### 📌 Summary")
                for note in high_db.summary_notes:
                    md.append(f"- {note}")
                md.append("")

            # A.1 Buy Triggers
            md.append("### 🔥 A.1 Stage 2 Buy Triggers (Actionable)")
            if high_db.watchlist_buy_triggers:
                md.append("| Symbol | Breakout Pivot | Trailing 20 EMA | Target 1 (+15%) | Target 2 (+30%) | Status |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
                for w in high_db.watchlist_buy_triggers:
                    md.append(
                        f"| **{w.symbol}** | ₹{w.pivot_high:.2f} | ₹{w.trailing_20ema:.2f} | "
                        f"₹{w.target_1_15pct:.2f} | ₹{w.target_2_30pct:.2f} | 🟢 **BUY TRIGGERED** |"
                    )
            else:
                md.append("*No watchlist stocks triggered Stage 2 buy confirmations today.*")
            md.append("")

            # A.2 Fresh Radar Breakouts
            md.append("### 📡 A.2 Fresh Breakout Radar")
            if high_db.new_radar_signals:
                md.append("| Symbol | High | Close | Vol Surge | Base Depth | ATR Ratio | T1 (+15%) | T2 (+30%) |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in high_db.new_radar_signals:
                    md.append(
                        f"| **{s.symbol}** | ₹{s.today_high:.2f} | ₹{s.breakout_price:.2f} | "
                        f"**{s.volume_ratio:.2f}x** | {s.base_metrics.base_depth_pct:.1f}% | "
                        f"{s.base_metrics.atr_contraction_ratio:.2f} | ₹{s.target_1_15pct:.2f} | ₹{s.target_2_30pct:.2f} |"
                    )
            else:
                md.append("*No fresh breakout candidates passed the 4-layer funnel today.*")
            md.append("")

            # A.3 Active Holdings
            md.append("### 🛡️ A.3 Active Holdings (Trailing 20 EMA)")
            if high_db.active_portfolio_status:
                md.append("| Symbol | Status | Entry Px | Current Px | PnL % | Trailing SL | Dist Trail |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                from src.scanner.models import HighStockStatusBadge
                badge_icons = {
                    HighStockStatusBadge.SAFE: "🟢 SAFE",
                    HighStockStatusBadge.TIGHTENING: "🟡 TIGHT",
                    HighStockStatusBadge.RADAR_ALERT: "⚠️ ALERT",
                    HighStockStatusBadge.DECISION_REQD: "🔴 DECISION",
                    HighStockStatusBadge.TARGET_1_HIT: "🎯 T1 HIT",
                    HighStockStatusBadge.TARGET_2_HIT: "🏆 T2 HIT",
                }
                for p in high_db.active_portfolio_status:
                    badge = badge_icons.get(p.status_badge, str(p.status_badge.value))
                    pnl = f"{'+' if p.unrealized_pnl_pct >= 0 else ''}{p.unrealized_pnl_pct:.2f}%"
                    dist_trail = ((p.current_price - p.trailing_sl) / p.trailing_sl) * 100
                    md.append(
                        f"| **{p.symbol}** | {badge} | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                        f"**{pnl}** | ₹{p.trailing_sl:.2f} | {dist_trail:+.1f}% |"
                    )
            else:
                md.append("*No active 52W High holdings.*")
            md.append("")

        elif briefing.get("high_error"):
            md.append("---")
            md.append(f"## 🚀 A. 52-Week HIGH — ⚠️ Error: {briefing['high_error']}")
            md.append("")

        # SECTION B: 52-WEEK LOW CAPITULATION
        if low_db is not None:
            md.append("---")
            md.append("")
            md.append("## 📉 B. 52-Week LOW — Capitulation Strategy (LONG)")
            md.append("")

            # B.1 Buy Triggers
            md.append("### 🟢 B.1 Watchlist Buy Triggers (Actionable)")
            if low_db.watchlist_buy_triggers:
                md.append("| Symbol | Capit. Low | Trigger Px | T1 (20 EMA) | T2 (50 EMA) | Notes |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
                for w in low_db.watchlist_buy_triggers:
                    px = f"₹{w.trigger_price:.2f}" if w.trigger_price else "Confirmed"
                    md.append(
                        f"| **{w.symbol}** | ₹{w.capitulation_low:.2f} | **{px}** | "
                        f"₹{w.target_1_20ema:.2f} | ₹{w.target_2_50ema:.2f} | {w.notes or '-'} |"
                    )
            else:
                md.append("*No watchlist stocks triggered Stage 2 buy today.*")
            md.append("")

            # B.2 Active Low Portfolio
            md.append("### 🛡️ B.2 Active Holdings Sentinel")
            if low_db.active_portfolio_status:
                md.append("| Symbol | Status | Entry Px | Current Px | PnL % | Dist SL | Remaining |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                from src.scanner.models import StockStatusBadge
                low_badge_icons = {
                    StockStatusBadge.SAFE: "🟢 SAFE",
                    StockStatusBadge.RADAR_ALERT: "🟡 RADAR",
                    StockStatusBadge.DECISION_REQD: "🔴 DECISION",
                    StockStatusBadge.TARGET_1_HIT: "🎯 T1 HIT",
                    StockStatusBadge.TARGET_2_HIT: "🏆 T2 HIT",
                }
                for p in low_db.active_portfolio_status:
                    badge = low_badge_icons.get(p.status_badge, str(p.status_badge.value))
                    pnl = f"{'+' if p.unrealized_pnl_pct >= 0 else ''}{p.unrealized_pnl_pct:.2f}%"
                    dist = f"{p.dist_from_sl_pct:+.1f}%"
                    md.append(
                        f"| **{p.symbol}** | {badge} | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                        f"**{pnl}** | {dist} | {p.remaining_quantity} |"
                    )
            else:
                md.append("*No active 52W Low holdings.*")
            md.append("")

            # B.3 New Capitulation Candidates
            md.append("### 📡 B.3 New Capitulation Candidates")
            if low_db.new_radar_signals:
                md.append("| Symbol | Day Low | Close | Vol Anomaly | Soft Stop | T1 | Insider |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in low_db.new_radar_signals:
                    insider_text = f"₹{s.insider_activity.value_inr/1e7:.1f} Cr" if s.insider_activity else "None"
                    md.append(
                        f"| **{s.symbol}** | ₹{s.low_price:.2f} | ₹{s.close_price:.2f} | "
                        f"**{s.volume_ratio:.2f}x** | ₹{s.support_sl:.2f} | ₹{s.target_1_20ema:.2f} | {insider_text} |"
                    )
            else:
                md.append("*No new capitulation signals today.*")
            md.append("")

        elif briefing.get("low_error"):
            md.append("---")
            md.append(f"## 📉 B. 52-Week LOW — ⚠️ Error: {briefing['low_error']}")
            md.append("")

        # SECTION C: 52-WEEK HIGH EXHAUSTION SHORT (INTRADAY MIS)
        if short_db is not None:
            md.append("---")
            md.append("")
            md.append("## 🔻 C. 52-Week HIGH EXHAUSTION — Intraday MIS Strategy (SHORT)")
            md.append("")

            # C.1 Day 2 & Day 3 Action Triggers
            md.append("### 🔥 C.1 Intraday MIS Breakdown Triggers (Actionable Today)")
            all_triggers = short_db.day2_mis_triggers + short_db.day3_continuation_triggers
            if all_triggers:
                md.append("| Symbol | Mode | Trigger Px | Hard Invalidation | Target 1 (-2%) | Target 2 (-4%) | Status |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for item in short_db.day2_mis_triggers:
                    md.append(
                        f"| **{item.symbol}** | Day 2 Initial | ₹{item.trigger_level_low:.2f} (Day 1 Low) | ₹{item.invalidation_level_high:.2f} | "
                        f"₹{item.target_1_mis:.2f} | ₹{item.target_2_mis:.2f} | 🔴 **DAY 2 MIS** |"
                    )
                for item in short_db.day3_continuation_triggers:
                    md.append(
                        f"| **{item.symbol}** | Day 3 Continuation | ₹{item.trigger_level_low:.2f} (Day 2 Low) | ₹{item.invalidation_level_high:.2f} | "
                        f"₹{item.target_1_mis:.2f} | ₹{item.target_2_mis:.2f} | ⚡ **DAY 3 CONT** |"
                    )
            else:
                md.append("*No watchlist stocks triggered Day 2 or Day 3 Intraday MIS breakdown today.*")
            md.append("")

            # C.2 Day 1 Climax Traps on Radar
            md.append("### 📡 C.2 Day 1 Climax Traps on Radar (Watch for Tomorrow Morning)")
            if short_db.new_climax_traps:
                md.append("| Symbol | 52W High | Day Low (Sell Trigger) | Vol Surge | Upper Wick | Parabolic 50 EMA | Action |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for sig in short_db.new_climax_traps:
                    md.append(
                        f"| **{sig.symbol}** | ₹{sig.climax_high:.2f} | **₹{sig.climax_low:.2f}** | **{sig.volume_ratio:.2f}x** | "
                        f"{sig.upper_wick_pct:.1f}% | +{sig.parabolic_extension_pct:.1f}% | Short on break below ₹{sig.climax_low:.2f} tomorrow |"
                    )
            else:
                md.append("*No fresh Day 1 Climax Traps detected on the tape today.*")
            md.append("")

        elif briefing.get("short_error"):
            md.append("---")
            md.append(f"## 🔻 C. 52-Week HIGH EXHAUSTION — ⚠️ Error: {briefing['short_error']}")
            md.append("")

        # INSIDER ACTIVITY SECTION (Section D if Short included, Section C if only High/Low)
        insider_trades = []
        if high_db and high_db.material_insider_trades:
            insider_trades.extend(high_db.material_insider_trades)
        if low_db and low_db.material_insider_trades:
            existing = {(t.symbol, t.filing_date) for t in insider_trades}
            for t in low_db.material_insider_trades:
                if (t.symbol, t.filing_date) not in existing:
                    insider_trades.append(t)

        if insider_trades:
            md.append("---")
            md.append("")
            sec_letter = "D" if short_db is not None else "C"
            md.append(f"## 💼 {sec_letter}. Material Promoter Buying (SEBI PIT ≥ ₹1 Cr)")
            md.append("| Symbol | Acquirer | Value | Filing Date | Mode |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for t in insider_trades[:10]:
                md.append(
                    f"| **{t.symbol}** | {t.acquirer_name} | **₹{t.value_inr/1e7:.2f} Cr** | "
                    f"{t.filing_date} | {t.acquisition_mode} |"
                )
            md.append("")

        md.append("---")
        md.append(f"*Generated by QuantCopilot Unified Scanner at {dt_str}*")
        return "\n".join(md)

    # -------------------------------------------------------------------------
    # UNIFIED MULTI-TABLE WATCHLIST ("52 watchlist")
    # -------------------------------------------------------------------------

    def get_unified_watchlist(self, strategy: str = "all") -> str:
        """Render automated separate tables for each strategy's watchlist."""
        lines = [
            "# 📋 QuantCopilot: Unified 52-Week Watchlist",
            "",
            "> Real-time monitoring across all 3 institutional strategy lifecycles.",
            "",
        ]

        # Table 1: 52-Week Low
        if strategy in ("all", "low"):
            lines.append("### 📉 1. 52-Week LOW (Capitulation Rebounds — LONG)")
            lines.append("*Monitoring for Stage 2 buy confirmation close above pivot / 5 EMA:*")
            low_wl = self.low.tracker.get_watchlist()
            if low_wl:
                lines.append("| Symbol | Capitulation Low (Support) | Trigger Pivot | Target 1 (20 EMA) | Target 2 (50 EMA) |")
                lines.append("| :--- | :--- | :--- | :--- | :--- |")
                for s in low_wl:
                    lines.append(
                        f"| **{s.symbol}** | ₹{s.capitulation_low:.2f} | ₹{s.capitulation_high:.2f} | "
                        f"₹{s.target_1_20ema:.2f} | ₹{s.target_2_50ema:.2f} |"
                    )
            else:
                lines.append("*No stocks currently on 52-Week Low Watchlist.*")
            lines.append("")

        # Table 2: 52-Week High Breakout
        if strategy in ("all", "high"):
            lines.append("### 🚀 2. 52-Week HIGH (Breakout Continuations — LONG)")
            lines.append("*Monitoring for Stage 2 breakout confirmation close above base pivot high:*")
            high_wl = self.high.tracker.get_watchlist()
            if high_wl:
                lines.append("| Symbol | Breakout Pivot | Trailing 20 EMA | Target 1 (+15%) | Target 2 (+30%) | Status |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in high_wl:
                    status_str = "🟢 BUY TRIGGERED" if s.is_buy_triggered else "⏳ MONITORING"
                    lines.append(
                        f"| **{s.symbol}** | ₹{s.pivot_high:.2f} | ₹{s.trailing_20ema:.2f} | "
                        f"₹{s.target_1_15pct:.2f} | ₹{s.target_2_30pct:.2f} | {status_str} |"
                    )
            else:
                lines.append("*No stocks currently on 52-Week High Watchlist.*")
            lines.append("")

        # Table 3: 52-Week High Exhaustion Short
        if strategy in ("all", "short"):
            lines.append("### 🔻 3. 52-Week HIGH EXHAUSTION (Day 2 & Day 3 Intraday MIS — SHORT)")
            lines.append("*Monitoring for breakdown below Day 1 Climax Low or Day 2 Continuation Low:*")
            short_wl = self.short.tracker.get_watchlist()
            if short_wl:
                lines.append("| Symbol | Mode | Sell Trigger Level | Hard Invalidation | Target 1 (-2%) | Target 2 (-4%) | Status |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in short_wl:
                    mode_str = "Day 3 Continuation" if s.is_continuation else "Day 2 Initial"
                    lines.append(
                        f"| **{s.symbol}** | {mode_str} | **₹{s.trigger_level_low:.2f}** | ₹{s.invalidation_level_high:.2f} | "
                        f"₹{s.target_1_mis:.2f} | ₹{s.target_2_mis:.2f} | {s.status.value} |"
                    )
            else:
                lines.append("*No stocks currently on 52-Week High Short Watchlist.*")
            lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # UNIFIED MULTI-TABLE PORTFOLIO ("52 portfolio")
    # -------------------------------------------------------------------------

    def get_unified_portfolio(
        self,
        strategy: str = "all",
        current_prices: Optional[Dict[str, float]] = None,
    ) -> str:
        """Render automated separate tables for Positional Longs vs Intraday Shorts."""
        lines = [
            "# 💼 QuantCopilot: Active 52-Week Portfolio",
            "",
            "> Automated risk sentinels and position lifecycle tracking.",
            "",
        ]

        # Table 1: Positional Long Holdings
        if strategy in ("all", "long", "low", "high"):
            lines.append("### 🟢 Positional Delivery Holdings (LONG)")
            low_port = self.low.tracker.get_portfolio()
            high_port = self.high.tracker.get_portfolio()

            if low_port or high_port:
                lines.append("| Symbol | Strategy | Entry Price | Current Price | PnL % | Status | Stop-Loss / Floor |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

                for p in low_port:
                    pnl_str = f"{'+' if p.unrealized_pnl_pct >= 0 else ''}{p.unrealized_pnl_pct:.2f}%"
                    badge_str = p.status_badge.value if hasattr(p.status_badge, "value") else str(p.status_badge)
                    lines.append(
                        f"| **{p.symbol}** | 52W Low | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                        f"**{pnl_str}** | {badge_str} | ₹{p.capitulation_low:.2f} |"
                    )

                for p in high_port:
                    pnl_str = f"{'+' if p.unrealized_pnl_pct >= 0 else ''}{p.unrealized_pnl_pct:.2f}%"
                    badge_str = p.status_badge.value if hasattr(p.status_badge, "value") else str(p.status_badge)
                    lines.append(
                        f"| **{p.symbol}** | 52W High | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                        f"**{pnl_str}** | {badge_str} | ₹{p.trailing_sl:.2f} |"
                    )
            else:
                lines.append("*No active positional long holdings.*")
            lines.append("")

        # Table 2: Active Intraday MIS Shorts
        if strategy in ("all", "short"):
            lines.append("### 🔴 Active Intraday MIS Positions (SHORT — Exit before 03:10 PM)")
            short_wl = self.short.tracker.get_watchlist()
            active_shorts = [s for s in short_wl if s.status.value == "TRIGGERED_MIS"]

            if active_shorts:
                lines.append("| Symbol | Strategy | Trigger Price | Hard SL | Target 1 (-2%) | Target 2 (-4%) | Status |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in active_shorts:
                    lines.append(
                        f"| **{s.symbol}** | 52W Short MIS | ₹{s.trigger_level_low:.2f} | ₹{s.invalidation_level_high:.2f} | "
                        f"₹{s.target_1_mis:.2f} | ₹{s.target_2_mis:.2f} | 🔴 ACTIVE MIS |"
                    )
            else:
                lines.append("*No active intraday MIS short positions currently open.*")
            lines.append("")

        return "\n".join(lines)
