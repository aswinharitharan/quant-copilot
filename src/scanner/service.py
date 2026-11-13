"""Unified Scanner Service Facade for 52-Week Low Strategy.

Ties together:
- Broad 52W-Low Discovery & Technical Engine (LowCapitulationScanner)
- Fundamental Solvency Audits (ScreenerClient)
- SEBI PIT Insider Transactions (InsiderFeed)
- 3-Tier Storage & Risk Sentinel (PortfolioTracker)
- Markdown Executive Briefing Generation
"""

import logging
import re
from datetime import datetime, timedelta, timezone
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
        tz: Optional[timezone] = None,
    ):
        # NOTE: Timezone logic defaults to IST (UTC+05:30) because the strategy exclusively
        # targets equities trading on the National Stock Exchange of India (NSE).
        # An optional `tz` argument is accepted for testing or multi-market flexibility.
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

        self.screener = screener_client or ScreenerClient(cache_dir=cache_dir)
        self.insider = insider_feed or InsiderFeed(cache_dir=cache_dir)
        self.tracker = PortfolioTracker(data_dir=data_dir)
        self.scanner = LowCapitulationScanner(
            cache_manager=self.cache_manager,
            screener_client=self.screener,
            insider_feed=self.insider,
            cache_dir=cache_dir,
        )

    IST = timezone(timedelta(hours=5, minutes=30))

    @classmethod
    def _today_ist(cls, tz: Optional[timezone] = None) -> str:
        """Return today's date in IST (YYYY-MM-DD)."""
        target_tz = tz or cls.IST
        return datetime.now(target_tz).date().isoformat()

    def _get_recent_daily_bars(
        self,
        symbol: str,
        as_of_date: Optional[str] = None,
        lookback_days: int = 60,
    ) -> Optional[pd.DataFrame]:
        """Fetch recent daily OHLCV candles for a symbol via cache_manager."""
        if not self.cache_manager:
            return None
        end_d = as_of_date or self._today_ist(self.tz)
        start_d = (pd.to_datetime(end_d) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        try:
            df = self.cache_manager.get_candles(
                symbol=symbol,
                exchange="NSE",
                interval="1d",
                start_date=start_d,
                end_date=end_d,
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Failed to fetch daily bars for {symbol}: {e}")
        return None

    def _fetch_latest_prices(
        self,
        symbols: List[str],
        as_of_date: Optional[str] = None,
    ) -> Dict[str, float]:
        """Fetch latest closing/traded price for each symbol from daily candles."""
        prices: Dict[str, float] = {}
        for sym in symbols:
            clean_sym = sym.upper()
            df = self._get_recent_daily_bars(clean_sym, as_of_date=as_of_date, lookback_days=15)
            if df is not None and not df.empty:
                col = "close" if "close" in df.columns else "Close"
                if col in df.columns:
                    prices[clean_sym] = round(float(df[col].iloc[-1]), 2)
        return prices

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
        try:
            dt_str = as_of_date or self._today_ist(self.tz)
            is_offline = current_prices is not None and not current_prices

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
                try:
                    updated_watchlist = self.scanner.check_watchlist(
                        watchlist,
                        lambda sym: self._get_recent_daily_bars(sym, as_of_date=dt_str),
                    )
                    self.tracker._save_watchlist(updated_watchlist)
                    triggered_watchlist = [s for s in updated_watchlist if s.is_buy_triggered]
                except Exception as e:
                    logger.warning(f"Error evaluating watchlist triggers: {e}")

            # 3. Sentinel Health Evaluation for Active Portfolio
            portfolio = self.tracker.get_portfolio()
            if portfolio:
                if current_prices is None:
                    current_prices = self._fetch_latest_prices([p.symbol for p in portfolio], as_of_date=dt_str)
                if current_prices:
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
            if is_offline:
                summary.append("Offline mode: live price auto-fetch skipped.")

            return DailyDashboard52(
                as_of_date=dt_str,
                new_radar_signals=new_signals,
                watchlist_buy_triggers=triggered_watchlist,
                active_portfolio_status=portfolio,
                material_insider_trades=insider_trades,
                summary_notes=summary,
            )
        except Exception as e:
            logger.exception("Unexpected error in get_daily_briefing", exc_info=e)
            raise

    def format_daily_briefing_markdown(self, dashboard: DailyDashboard52) -> str:
        """Render the DailyDashboard52 object into an executive Markdown briefing."""
        try:
            is_offline = any("Offline mode" in s for s in dashboard.summary_notes)
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

                    curr_px_str = "price N/A" if is_offline else f"₹{p.current_price:.2f}"
                    pnl_str = "N/A" if is_offline else f"**{p.unrealized_pnl_pct:+.2f}%**"
                    dist_str = "N/A" if is_offline else f"{p.dist_from_sl_pct:+.1f}%"

                    md.append(
                        f"| **{p.symbol}** | {badge_icon} | ₹{p.entry_price:.2f} | {curr_px_str} | {dist_str} | {pnl_str} | {p.remaining_quantity} |"
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
        except Exception as e:
            logger.exception("Unexpected error in format_daily_briefing_markdown", exc_info=e)
            raise

    # -------------------------------------------------------------------------
    # 2. MODULAR FAST QUERIES (LIGHTWEIGHT)
    # -------------------------------------------------------------------------

    def scan_radar_candidates(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[CapitulationSignal], str]:
        """Scan, filter, and audit 52-week low capitulation candidates only.
        
        Does NOT touch active portfolio or watchlist triggers.
        Focused strictly on discovery, volume anomaly verification, and fundamental solvency.
        """
        try:
            dt_str = as_of_date or self._today_ist(self.tz)
            signals = self.scanner.run_funnel_scan(
                candidate_symbols=candidate_symbols,
                as_of_date=as_of_date,
            )

            lines: List[str] = [
                f"# 📡 52-Week Low Capitulation Radar ({dt_str})",
                f"Evaluated candidate universe for 52W lows, volume anomalies (≥ 3x), and 5 Golden Solvency Rules.",
                "",
            ]

            if signals:
                lines.append("| Symbol | Day Low | Day Close | Volume Ratio | Support SL | Target 1 (20 EMA) | Target 2 (50 EMA) | Audit Result | Promoter Buying |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for s in signals:
                    insider_text = f"₹{s.insider_activity.value_inr/1e7:.1f} Cr" if s.insider_activity else "None"
                    audit_summary = f"D/E: {s.audit.debt_to_equity}, ROCE: {s.audit.roce_pct}%"
                    lines.append(
                        f"| **{s.symbol}** | ₹{s.low_price:.2f} | ₹{s.close_price:.2f} | **{s.volume_ratio:.2f}x** | ₹{s.support_sl:.2f} | ₹{s.target_1_20ema:.2f} | ₹{s.target_2_50ema:.2f} | ✅ {audit_summary} | {insider_text} |"
                    )
                lines.append("")
                lines.append("💡 *To shortlist any of these stocks, tell your copilot: `Add <SYMBOL> to 52 watchlist`.*")
            else:
                lines.append("*No stocks met both the 52W low volume anomaly ($3x$) and the 5 Golden Solvency Rules today.*")

            return signals, "\n".join(lines)
        except Exception as e:
            logger.exception("Unexpected error in scan_radar_candidates", exc_info=e)
            raise

    def get_portfolio_summary(
        self,
        current_prices: Optional[Dict[str, float]] = None,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[PortfolioStock], str]:
        """Fast portfolio check with automatic latest-price refresh."""
        try:
            portfolio = self.tracker.get_portfolio()
            if not portfolio:
                return [], "🛡️ **Active Portfolio**: 0 open positions."

            is_offline = current_prices is not None and not current_prices

            if current_prices is None:
                current_prices = self._fetch_latest_prices([p.symbol for p in portfolio], as_of_date=as_of_date)

            if current_prices:
                portfolio = self.tracker.evaluate_portfolio_health(current_prices)

            lines = [f"🛡️ **Active Portfolio Status** ({len(portfolio)} holdings):"]
            for p in portfolio:
                badge_icon = {
                    StockStatusBadge.SAFE: "🟢 SAFE",
                    StockStatusBadge.RADAR_ALERT: "🟡 RADAR ALERT",
                    StockStatusBadge.DECISION_REQD: "🔴 DECISION REQD",
                    StockStatusBadge.TARGET_1_HIT: "🎯 TARGET 1 HIT",
                    StockStatusBadge.TARGET_2_HIT: "🏆 TARGET 2 HIT",
                }.get(p.status_badge, str(p.status_badge.value))

                if is_offline:
                    curr_str = "Current: price N/A | "
                    pnl_str = ""
                    dist_str = f"SL: ₹{p.capitulation_low:.2f} | "
                else:
                    unrealized_inr = (p.current_price - p.entry_price) * p.remaining_quantity
                    curr_str = f"Current: ₹{p.current_price:.2f} | "
                    pnl_str = f"PnL: {p.unrealized_pnl_pct:+.2f}% (₹{unrealized_inr:+,.2f}) | "
                    dist_str = f"SL: ₹{p.capitulation_low:.2f} ({p.dist_from_sl_pct:+.1f}%) | "

                lines.append(
                    f"- **{p.symbol}**: {badge_icon} | {curr_str}Entry: ₹{p.entry_price:.2f} | "
                    f"{pnl_str}"
                    f"{dist_str}"
                    f"T1: ₹{p.target_1_20ema:.2f} | T2: ₹{p.target_2_50ema:.2f} | Qty: {p.remaining_quantity}"
                )
                if p.history_notes:
                    lines.append(f"  *Latest Note*: {p.history_notes[-1]}")

            return portfolio, "\n".join(lines)
        except Exception as e:
            logger.exception("Unexpected error in get_portfolio_summary", exc_info=e)
            raise

    def get_watchlist_summary(self, as_of_date: Optional[str] = None) -> Tuple[List[WatchlistStock], str]:
        """Review Tier 1 Watchlist with automatic Stage 2 trigger evaluation and latest prices."""
        try:
            watchlist = self.tracker.get_watchlist()
            if not watchlist:
                return [], "📋 **Watchlist**: 0 stocks currently watched."

            bars_map: Dict[str, Optional[pd.DataFrame]] = {}
            for w in watchlist:
                bars_map[w.symbol] = self._get_recent_daily_bars(w.symbol, as_of_date=as_of_date)

            if any(df is not None for df in bars_map.values()):
                watchlist = self.scanner.check_watchlist(watchlist, lambda sym: bars_map.get(sym))
                self.tracker._save_watchlist(watchlist)

            lines = [f"📋 **Tier 1 Watchlist** ({len(watchlist)} stocks):"]
            for w in watchlist:
                df = bars_map.get(w.symbol)
                latest_px_str = ""
                if df is not None and not df.empty:
                    col = "close" if "close" in df.columns else "Close"
                    if col in df.columns:
                        latest_px_str = f"Current: ₹{float(df[col].iloc[-1]):.2f} | "

                if w.is_buy_triggered:
                    trig_info = f" on {w.trigger_date}" if w.trigger_date else ""
                    trig_px = f" @ ₹{w.trigger_price:.2f}" if w.trigger_price else ""
                    status = f"🟢 BUY TRIGGERED{trig_info}{trig_px}"
                else:
                    status = "⏳ Awaiting Stage 2"

                lines.append(
                    f"- **{w.symbol}** ({status}): {latest_px_str}Pivot High: ₹{w.capitulation_high:.2f} | "
                    f"Support SL: ₹{w.capitulation_low:.2f} | "
                    f"T1 (20 EMA): ₹{w.target_1_20ema:.2f} | T2 (50 EMA): ₹{w.target_2_50ema:.2f} | Notes: '{w.notes or '-'}'"
                )

            return watchlist, "\n".join(lines)
        except Exception as e:
            logger.exception("Unexpected error in get_watchlist_summary", exc_info=e)
            raise

    def audit_single_symbol(self, symbol: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Deep dive on a single symbol: fundamentals, insider activity, and technical levels."""
        try:
            clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

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
        except Exception as e:
            logger.exception("Unexpected error in audit_single_symbol", exc_info=e)
            raise

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
        try:
            return self.tracker.record_buy(
                symbol=symbol,
                entry_price=entry_price,
                quantity=quantity,
                entry_date=entry_date,
                notes=notes,
            )
        except Exception as e:
            logger.exception("Unexpected error in record_buy", exc_info=e)
            raise

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
        try:
            return self.tracker.record_partial_sell(
                symbol=symbol,
                sell_price=sell_price,
                quantity=quantity,
                reason=reason,
                sell_date=sell_date,
                notes=notes,
            )
        except Exception as e:
            logger.exception("Unexpected error in record_sell", exc_info=e)
            raise

    def add_to_watchlist(
        self,
        symbol: str,
        user_notes: Optional[str] = None,
        as_of_date: Optional[str] = None,
    ) -> Optional[WatchlistStock]:
        """Scan candidate symbol and add to Tier 1 Watchlist if valid signal found."""
        try:
            clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
            if not re.fullmatch(r"[A-Z0-9_]{1,20}", clean_sym):
                logger.error("Invalid symbol: %s", clean_sym)
                return None

            sig = self.scanner.scan_candidate(clean_sym, as_of_date=as_of_date)
            if sig is None:
                logger.warning(f"Could not generate capitulation signal for {clean_sym}")
                return None
            return self.tracker.add_to_watchlist(
                sig,
                user_notes=user_notes,
                added_date=as_of_date or self._today_ist(self.tz),
            )
        except Exception as e:
            logger.exception("Unexpected error in add_to_watchlist", exc_info=e)
            raise

    def remove_from_watchlist(self, symbol: str) -> bool:
        """Remove symbol from Tier 1 Watchlist."""
        try:
            clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
            return self.tracker.remove_from_watchlist(clean_sym)
        except Exception as e:
            logger.exception("Unexpected error in remove_from_watchlist", exc_info=e)
            raise
