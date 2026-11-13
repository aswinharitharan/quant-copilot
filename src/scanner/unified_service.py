"""Unified 52-Week Scanner Service — orchestrates both High & Low strategies.

This is the single entry point for:
    "whats today for 52" → Runs BOTH 52W Low Capitulation + 52W High Breakout strategies
                           and merges into a combined executive briefing.

Also supports:
    --strategy high  → Only 52W High Breakout
    --strategy low   → Only 52W Low Capitulation
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.scanner.high_service import HighScannerService
from src.scanner.service import ScannerService

logger = logging.getLogger(__name__)


class UnifiedScannerService:
    """Orchestrates both 52-Week Low and 52-Week High strategies."""

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
    ):
        self.tz = tz or self.IST

        # Build or accept sub-services
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
        strategy: str = "both",  # "both", "high", "low"
        skip_fundamental_audit: bool = False,
    ) -> Dict[str, Any]:
        """Run both strategies and return raw dashboard payloads.

        Returns:
            dict with keys 'low_dashboard', 'high_dashboard', 'as_of_date'.
            Whichever strategy is skipped will have None for its dashboard.
        """
        dt_str = as_of_date or self._today_ist(self.tz)
        result: Dict[str, Any] = {
            "as_of_date": dt_str,
            "low_dashboard": None,
            "high_dashboard": None,
        }

        if strategy in ("both", "low"):
            try:
                result["low_dashboard"] = self.low.get_daily_briefing(
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                    skip_fundamental_audit=skip_fundamental_audit,
                )
            except Exception as e:
                logger.warning(f"52W Low briefing error: {e}")
                result["low_error"] = str(e)

        if strategy in ("both", "high"):
            try:
                result["high_dashboard"] = self.high.get_daily_briefing(
                    candidate_symbols=candidate_symbols,
                    as_of_date=as_of_date,
                    skip_fundamental_audit=skip_fundamental_audit,
                )
            except Exception as e:
                logger.warning(f"52W High briefing error: {e}")
                result["high_error"] = str(e)

        return result

    def format_unified_briefing_markdown(
        self,
        briefing: Dict[str, Any],
    ) -> str:
        """Merge both strategy dashboards into a single executive markdown briefing."""
        dt_str = briefing["as_of_date"]
        low_db = briefing.get("low_dashboard")
        high_db = briefing.get("high_dashboard")

        md: List[str] = [
            f"# 📊 QuantCopilot: Unified 52-Week Briefing — {dt_str}",
            "",
            "> **Dual Strategy**: 52W High Breakout + 52W Low Capitulation",
            "",
        ]

        # ═══════════════════════════════════════════════════════════════
        # SECTION A: 52-WEEK HIGH BREAKOUT
        # ═══════════════════════════════════════════════════════════════
        if high_db is not None:
            md.append("---")
            md.append("")
            md.append("## 🚀 A. 52-Week HIGH — Breakout Strategy")
            md.append("")

            # A.1 Summary
            if high_db.summary_notes:
                md.append("### 📌 Summary")
                for note in high_db.summary_notes:
                    md.append(f"- {note}")
                md.append("")

            # A.2 Stage 2 Buy Triggers
            md.append("### 🔥 A.1 Stage 2 Buy Triggers (Actionable)")
            if high_db.watchlist_buy_triggers:
                md.append("| Symbol | Breakout Date | Trigger Px | Pivot High | Initial SL | T1 (+15%) | T2 (+30%) |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for w in high_db.watchlist_buy_triggers:
                    md.append(
                        f"| **{w.symbol}** | {w.breakout_date} | **₹{w.trigger_price or 0:.2f}** | "
                        f"₹{w.pivot_high:.2f} | ₹{w.initial_sl:.2f} | ₹{w.target_1_15pct:.2f} | ₹{w.target_2_30pct:.2f} |"
                    )
            else:
                md.append("*No watchlist stocks triggered Stage 2 buy confirmations today.*")
            md.append("")

            # A.3 Fresh Breakout Radar
            md.append("### 📡 A.2 Fresh Breakout Radar")
            if high_db.new_radar_signals:
                md.append("| Symbol | Close Px | 52W High | Vol Ratio | Base Days | Base Depth | Trailing SL | T1 |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in high_db.new_radar_signals:
                    md.append(
                        f"| **{s.symbol}** | ₹{s.breakout_price:.2f} | ₹{s.high_52w:.2f} | "
                        f"**{s.volume_ratio:.2f}x** | {s.base_metrics.base_duration_days}d | "
                        f"-{s.base_metrics.base_depth_pct:.1f}% | ₹{s.initial_sl:.2f} | ₹{s.target_1_15pct:.2f} |"
                    )
            else:
                md.append("*No fresh breakout candidates passed the 4-layer funnel today.*")
            md.append("")

            # A.4 Active High Portfolio
            md.append("### 🛡️ A.3 Active Holdings (Trailing 20 EMA)")
            if high_db.active_portfolio_status:
                md.append("| Symbol | Entry Px | Current Px | PnL % | Trailing SL | Status |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
                from src.scanner.models import HighStockStatusBadge
                badge_icons = {
                    HighStockStatusBadge.SAFE: "🟢 SAFE",
                    HighStockStatusBadge.TIGHTENING: "🟡 TIGHTEN",
                    HighStockStatusBadge.RADAR_ALERT: "🟠 RADAR",
                    HighStockStatusBadge.DECISION_REQD: "🔴 DECISION",
                    HighStockStatusBadge.TARGET_1_HIT: "🎯 T1 HIT",
                    HighStockStatusBadge.TARGET_2_HIT: "🏆 T2 HIT",
                }
                for p in high_db.active_portfolio_status:
                    badge = badge_icons.get(p.status_badge, p.status_badge.value)
                    pnl = f"{'+' if p.unrealized_pnl_pct >= 0 else ''}{p.unrealized_pnl_pct:.2f}%"
                    md.append(
                        f"| **{p.symbol}** | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                        f"**{pnl}** | ₹{p.trailing_sl:.2f} | {badge} |"
                    )
            else:
                md.append("*No active 52W High holdings.*")
            md.append("")

        elif briefing.get("high_error"):
            md.append("---")
            md.append(f"## 🚀 A. 52-Week HIGH — ⚠️ Error: {briefing['high_error']}")
            md.append("")

        # ═══════════════════════════════════════════════════════════════
        # SECTION B: 52-WEEK LOW CAPITULATION
        # ═══════════════════════════════════════════════════════════════
        if low_db is not None:
            md.append("---")
            md.append("")
            md.append("## 📉 B. 52-Week LOW — Capitulation Strategy")
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

        # ═══════════════════════════════════════════════════════════════
        # SECTION C: COMBINED INSIDER ACTIVITY
        # ═══════════════════════════════════════════════════════════════
        insider_trades = []
        if high_db and high_db.material_insider_trades:
            insider_trades.extend(high_db.material_insider_trades)
        if low_db and low_db.material_insider_trades:
            # Deduplicate by (symbol, filing_date)
            existing = {(t.symbol, t.filing_date) for t in insider_trades}
            for t in low_db.material_insider_trades:
                if (t.symbol, t.filing_date) not in existing:
                    insider_trades.append(t)

        if insider_trades:
            md.append("---")
            md.append("")
            md.append("## 💼 C. Material Promoter Buying (SEBI PIT ≥ ₹1 Cr)")
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

