"""Unified Scanner Service Facade for 52-Week Low Strategy.

Ties together:
- Broad 52W-Low Discovery & Technical Engine (LowCapitulationScanner)
- Fundamental Solvency Audits (ScreenerClient)
- SEBI PIT Insider Transactions (InsiderFeed)
- 3-Tier Storage & Risk Sentinel (PortfolioTracker)
- Markdown Executive Briefing Generation
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from src.scanner.insider_feed import InsiderFeed
from src.scanner.low_scanner import LowCapitulationScanner
from src.scanner.models import (
    CapitulationSignal,
    ClosedTradeLedger,
    DailyDashboard52,
    FundamentalAudit,
    InsiderTradeRecord,
    PortfolioStock,
    SellReason,
    SignalStage,
    StockStatusBadge,
    WatchlistStock,
)
from src.scanner.screener_client import ScreenerClient
from src.scanner.tracker import PortfolioTracker

logger = logging.getLogger(__name__)


class ScannerService:
    """Unified Facade managing the 52-Week Low Capitulation Strategy."""

    def __init__(
        self,
        cache_dir: str = "data/cache",
        data_dir: str = "data",
        cache_manager: Optional[Any] = None,
        screener_client: Optional[ScreenerClient] = None,
        insider_feed: Optional[InsiderFeed] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.data_dir = Path(data_dir)
        self.cache_manager = cache_manager

        self.screener = screener_client or ScreenerClient(cache_dir=cache_dir)
        self.insider = insider_feed or InsiderFeed(cache_dir=cache_dir)
        self.tracker = PortfolioTracker(data_dir=data_dir)
        self.scanner = LowCapitulationScanner(
            cache_manager=cache_manager,
            screener_client=self.screener,
            insider_feed=self.insider,
            cache_dir=cache_dir,
        )

    # -------------------------------------------------------------------------
    # 1. DAILY BRIEFING ("Whats today for 52")
    # -------------------------------------------------------------------------

    def get_daily_briefing(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
        current_prices: Optional[Dict[str, float]] = None,
    ) -> DailyDashboard52:
        """Run full end-to-end evening dashboard.
        
        1. Discovers new Stage 1 Capitulation Signals
        2. Evaluates Watchlist for Stage 2 Buy Triggers
        3. Runs Daily Sentinel over Active Portfolio
        4. Correlates material insider disclosures
        """
        dt_str = as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. New Stage 1 Signals
        new_signals: List[CapitulationSignal] = []
        try:
            new_signals = self.scanner.run_funnel_scan(
                candidate_symbols=candidate_symbols,
                as_of_date=as_of_date,
                skip_fundamental_audit=skip_fundamental_audit,
            )
        except Exception as e:
            logger.warning(f"Error during funnel scan: {e}")

        # 2. Check Watchlist for Stage 2 confirmation triggers
        watchlist = self.tracker.get_watchlist()
        triggered_watchlist: List[WatchlistStock] = []
        if watchlist:
            def _get_bars(sym: str) -> Optional[pd.DataFrame]:
                if self.cache_manager:
                    return self.cache_manager.get_candles(
                        symbol=sym,
                        exchange="NSE",
                        interval="1d",
                        start_date=(pd.to_datetime(dt_str) - pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
                        end_date=dt_str,
                    )
                return None

            try:
                updated_watchlist = self.scanner.check_watchlist(watchlist, _get_bars)
                self.tracker._save_watchlist(updated_watchlist)
                triggered_watchlist = [s for s in updated_watchlist if s.is_buy_triggered]
            except Exception as e:
                logger.warning(f"Error evaluating watchlist triggers: {e}")

        # 3. Sentinel Health Evaluation for Active Portfolio
        portfolio = self.tracker.get_portfolio()
        if portfolio and current_prices:
            portfolio = self.tracker.evaluate_portfolio_health(current_prices)

        # 4. Material Insider Trades
        insider_trades: List[InsiderTradeRecord] = []
        try:
            all_pit = self.insider.fetch_nse_pit()
            insider_trades = [r for r in all_pit if r.is_material_promoter_buy][:10]
        except Exception as e:
            logger.warning(f"Error fetching insider trades: {e}")

        summary: List[str] = [
            f"52-Week Low Strategy Briefing as of {dt_str}.",
            f"Found {len(new_signals)} new capitulation radar candidates.",
            f"{len(triggered_watchlist)} stocks on Watchlist confirmed Stage 2 BUY.",
            f"Monitoring {len(portfolio)} active positions in Portfolio.",
        ]

        return DailyDashboard52(
            as_of_date=dt_str,
            new_radar_signals=new_signals,
            watchlist_buy_triggers=triggered_watchlist,
            active_portfolio_status=portfolio,
            material_insider_trades=insider_trades,
            summary_notes=summary,
        )

    def format_daily_briefing_markdown(self, dashboard: DailyDashboard52) -> str:
        """Render the DailyDashboard52 object into an executive Markdown briefing."""
        md: List[str] = [
            f"# 🎯 52-Week Low Capitulation Briefing ({dashboard.as_of_date})",
            "",
        ]

        # Section 1: Watchlist Buy Triggers (Highest Priority!)
        md.append("## 🟢 1. Watchlist Stage 2 Buy Triggers (Actionable Today)")
        if dashboard.watchlist_buy_triggers:
            md.append("| Symbol | Capitulation Low | Trigger Price | Target 1 (20 EMA) | Target 2 (50 EMA) | Notes |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for w in dashboard.watchlist_buy_triggers:
                px = f"₹{w.trigger_price:.2f}" if w.trigger_price else "Confirmed"
                md.append(
                    f"| **{w.symbol}** | ₹{w.capitulation_low:.2f} | **{px}** | ₹{w.target_1_20ema:.2f} | ₹{w.target_2_50ema:.2f} | {w.notes or '-'} |"
                )
        else:
            md.append("*No watchlist stocks triggered Stage 2 today. Continue holding watchlist.*")
        md.append("")

        # Section 2: Active Portfolio Health & Sentinels
        md.append("## 🛡️ 2. Active Portfolio Sentinel Status")
        if dashboard.active_portfolio_status:
            md.append("| Symbol | Status Badge | Entry Px | Current Px | Dist from SL | PnL % | Remaining Qty |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for p in dashboard.active_portfolio_status:
                badge_icon = {
                    StockStatusBadge.SAFE: "🟢 SAFE",
                    StockStatusBadge.RADAR_ALERT: "🟡 RADAR ALERT",
                    StockStatusBadge.DECISION_REQD: "🔴 DECISION REQD",
                    StockStatusBadge.TARGET_1_HIT: "🎯 TARGET 1 HIT",
                    StockStatusBadge.TARGET_2_HIT: "🏆 TARGET 2 HIT",
                }.get(p.status_badge, str(p.status_badge.value))

                md.append(
                    f"| **{p.symbol}** | {badge_icon} | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | {p.dist_from_sl_pct:+.1f}% | **{p.unrealized_pnl_pct:+.2f}%** | {p.remaining_quantity} |"
                )
        else:
            md.append("*No open positions in active portfolio.*")
        md.append("")

        # Section 3: New Stage 1 Capitulation Radar Signals
        md.append("## 📡 3. New Stage 1 Capitulation Candidates (Discovered Today)")
        if dashboard.new_radar_signals:
            md.append("| Symbol | Day Low | Day Close | Volume Anomaly | Soft Stop | Target 1 | Promoter Buying |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for s in dashboard.new_radar_signals:
                insider_text = f"₹{s.insider_activity.value_inr/1e7:.1f} Cr" if s.insider_activity else "None"
                md.append(
                    f"| **{s.symbol}** | ₹{s.low_price:.2f} | ₹{s.close_price:.2f} | **{s.volume_ratio:.2f}x** | ₹{s.support_sl:.2f} | ₹{s.target_1_20ema:.2f} | {insider_text} |"
                )
        else:
            md.append("*No new stocks met both the 52W low volume anomaly ($3x$) and 5 Golden Solvency Rules today.*")
        md.append("")

        # Section 4: Material Insider Trades
        if dashboard.material_insider_trades:
            md.append("## 🏢 4. Material Promoter Open-Market Purchases (SEBI PIT)")
            md.append("| Symbol | Acquirer | Mode | Value (INR) | Filing Date |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for it in dashboard.material_insider_trades[:5]:
                md.append(
                    f"| **{it.symbol}** | {it.acquirer_name} | {it.acquisition_mode} | **₹{it.value_inr/1e7:.2f} Cr** | {it.filing_date} |"
                )
            md.append("")

        return "\n".join(md)

    # -------------------------------------------------------------------------
    # 2. MODULAR FAST QUERIES (LIGHTWEIGHT)
    # -------------------------------------------------------------------------

    def get_portfolio_summary(self, current_prices: Optional[Dict[str, float]] = None) -> Tuple[List[PortfolioStock], str]:
        """Fast (< 1s) portfolio check without running any market scans."""
        portfolio = self.tracker.get_portfolio()
        if portfolio and current_prices:
            portfolio = self.tracker.evaluate_portfolio_health(current_prices)

        if not portfolio:
            return [], "🛡️ **Active Portfolio**: 0 open positions."

        lines = [f"🛡️ **Active Portfolio Status** ({len(portfolio)} holdings):"]
        for p in portfolio:
            badge_icon = {
                StockStatusBadge.SAFE: "🟢 SAFE",
                StockStatusBadge.RADAR_ALERT: "🟡 RADAR ALERT",
                StockStatusBadge.DECISION_REQD: "🔴 DECISION REQD",
                StockStatusBadge.TARGET_1_HIT: "🎯 TARGET 1 HIT",
                StockStatusBadge.TARGET_2_HIT: "🏆 TARGET 2 HIT",
            }.get(p.status_badge, str(p.status_badge.value))

            lines.append(
                f"- **{p.symbol}**: {badge_icon} | Current: ₹{p.current_price:.2f} | Entry: ₹{p.entry_price:.2f} | "
                f"PnL: {p.unrealized_pnl_pct:+.2f}% | SL: ₹{p.capitulation_low:.2f} ({p.dist_from_sl_pct:+.1f}%) | "
                f"Qty: {p.remaining_quantity}"
            )
            if p.history_notes:
                lines.append(f"  *Latest Note*: {p.history_notes[-1]}")

        return portfolio, "\n".join(lines)

    def get_watchlist_summary(self) -> Tuple[List[WatchlistStock], str]:
        """Fast (< 1s) review of Tier 1 Watchlist."""
        watchlist = self.tracker.get_watchlist()
        if not watchlist:
            return [], "📋 **Watchlist**: 0 stocks currently watched."

        lines = [f"📋 **Tier 1 Watchlist** ({len(watchlist)} stocks):"]
        for w in watchlist:
            status = "🟢 BUY TRIGGERED" if w.is_buy_triggered else "⏳ Awaiting Stage 2"
            lines.append(
                f"- **{w.symbol}** ({status}): Capitulation Low: ₹{w.capitulation_low:.2f} | "
                f"T1 (20 EMA): ₹{w.target_1_20ema:.2f} | T2 (50 EMA): ₹{w.target_2_50ema:.2f} | Notes: '{w.notes or '-'}'"
            )

        return watchlist, "\n".join(lines)

    def audit_single_symbol(self, symbol: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Deep dive on a single symbol: fundamentals, insider activity, and technical levels."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")

        # 1. Fundamental audit
        audit = self.screener.audit_company(clean_sym)

        # 2. Insider trade
        insider = self.insider.get_symbol_insider_activity(clean_sym)

        # 3. Technical levels if df provided or cached
        tech_levels = None
        if df is not None:
            tech_levels = self.scanner.calculate_technical_levels(df)

        return {
            "symbol": clean_sym,
            "fundamental_audit": audit,
            "insider_activity": insider,
            "technical_levels": tech_levels,
        }

    # -------------------------------------------------------------------------
    # 3. TRADE LOGGING PROXIES
    # -------------------------------------------------------------------------

    def record_buy(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        entry_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> PortfolioStock:
        """Register buy order into Active Portfolio."""
        return self.tracker.record_buy(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            entry_date=entry_date,
            notes=notes,
        )

    def record_sell(
        self,
        symbol: str,
        sell_price: float,
        quantity: int,
        reason: SellReason,
        sell_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Tuple[PortfolioStock, Optional[ClosedTradeLedger]]:
        """Record partial or full sell of active holding."""
        return self.tracker.record_partial_sell(
            symbol=symbol,
            sell_price=sell_price,
            quantity=quantity,
            reason=reason,
            sell_date=sell_date,
            notes=notes,
        )
