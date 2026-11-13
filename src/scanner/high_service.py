"""Unified Facade Service for 52-Week High Breakout Strategy.

Provides the single entry point for:
- "Whats today for 52 High" executive briefing
- 4-Layer Breakout Funnel discovery
- Tier 1 Watchlist & Stage 2 confirmation monitoring
- Tier 2 Active Portfolio tracking with trailing 20 EMA ratchet
- Fundamental growth audits & SEBI PIT insider activity
- Order recording (buy/sell) & Tier 3 trade ledger archiving
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.scanner.high_scanner import HighBreakoutScanner
from src.scanner.high_tracker import HighPortfolioTracker
from src.scanner.insider_feed import InsiderFeed
from src.scanner.models import (
    BreakoutSignal,
    ClosedTradeLedger,
    DailyDashboard52High,
    FundamentalAudit,
    HighPortfolioStock,
    HighStockStatusBadge,
    HighWatchlistStock,
    InsiderTradeRecord,
    SellReason,
)
from src.scanner.screener_client import ScreenerClient

logger = logging.getLogger(__name__)


class HighScannerService:
    """Unified Facade managing the 52-Week High Breakout Strategy."""

    IST = timezone(timedelta(hours=5, minutes=30))

    def __init__(
        self,
        cache_dir: str = "data/cache",
        data_dir: str = "data",
        cache_manager: Optional[Any] = None,
        screener_client: Optional[ScreenerClient] = None,
        insider_feed: Optional[InsiderFeed] = None,
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

        self.screener = screener_client or ScreenerClient(cache_dir=cache_dir)
        self.insider = insider_feed or InsiderFeed(cache_dir=cache_dir)
        self.tracker = HighPortfolioTracker(data_dir=data_dir)
        self.scanner = HighBreakoutScanner(
            cache_manager=self.cache_manager,
            screener_client=self.screener,
            insider_feed=self.insider,
            cache_dir=cache_dir,
        )

    @classmethod
    def _today_ist(cls, tz: Optional[timezone] = None) -> str:
        """Return today's date in IST (YYYY-MM-DD)."""
        target_tz = tz or cls.IST
        return datetime.now(target_tz).date().isoformat()

    def _get_recent_daily_bars(
        self,
        symbol: str,
        as_of_date: Optional[str] = None,
        lookback_days: int = 120,
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

    def _fetch_latest_prices_and_emas(
        self,
        symbols: List[str],
        as_of_date: Optional[str] = None,
    ) -> Dict[str, Tuple[float, float]]:
        """Fetch latest closing price and 20 EMA for each symbol."""
        res: Dict[str, Tuple[float, float]] = {}
        for sym in symbols:
            clean_sym = sym.upper()
            df = self._get_recent_daily_bars(clean_sym, as_of_date=as_of_date, lookback_days=45)
            if df is not None and not df.empty:
                last_px = float(df["close"].iloc[-1])
                ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1]) if len(df) >= 5 else last_px
                res[clean_sym] = (round(last_px, 2), round(ema20, 2))
        return res

    # -------------------------------------------------------------------------
    # DAILY BRIEFING ("Whats today for 52 High")
    # -------------------------------------------------------------------------

    def get_daily_briefing(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
        skip_fundamental_audit: bool = False,
        current_prices_and_emas: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> DailyDashboard52High:
        """Generate the complete executive daily briefing payload."""
        dt_str = as_of_date or self._today_ist(self.tz)
        summary_notes: List[str] = []

        # 1. Update active portfolio with latest prices and ratcheted trailing stops
        portfolio = self.tracker.get_portfolio()
        if portfolio:
            price_map = current_prices_and_emas or self._fetch_latest_prices_and_emas(
                [p.symbol for p in portfolio], as_of_date=as_of_date
            )
            portfolio = self.tracker.update_portfolio_prices(price_map, as_of_date=dt_str)
            summary_notes.append(f"Monitored {len(portfolio)} active 52W High holding(s) with trailing 20 EMA.")

        # 2. Check active Watchlist for Stage 2 Buy Confirmations
        watchlist = self.tracker.get_watchlist()
        triggered_watchlist: List[HighWatchlistStock] = []
        if watchlist:
            watchlist = self.scanner.check_watchlist(
                watchlist,
                get_daily_bars_fn=lambda s: self._get_recent_daily_bars(s, as_of_date=as_of_date, lookback_days=30),
            )
            self.tracker._save_watchlist(watchlist)
            triggered_watchlist = [w for w in watchlist if w.is_buy_triggered]
            if triggered_watchlist:
                summary_notes.append(
                    f"🔥 {len(triggered_watchlist)} stock(s) triggered Stage 2 Buy Confirmation today!"
                )

        # 3. Discovery: Scan candidate symbols through the 4-layer breakout funnel
        new_signals: List[BreakoutSignal] = []
        try:
            new_signals = self.scanner.run_funnel_scan(
                candidate_symbols=candidate_symbols,
                as_of_date=as_of_date,
                skip_fundamental_audit=skip_fundamental_audit,
            )
            if new_signals:
                summary_notes.append(
                    f"Found {len(new_signals)} fresh 52W High breakout(s) from valid consolidation bases."
                )
            else:
                summary_notes.append("No fresh breakout candidates passed the 4-layer funnel today.")
        except Exception as e:
            logger.warning(f"Error during breakout discovery scan: {e}")
            summary_notes.append(f"Breakout discovery scan encountered error: {e}")

        # 4. Check Insider Buying
        insider_trades = []
        if hasattr(self.insider, "get_recent_material_promoter_buys"):
            try:
                insider_trades = self.insider.get_recent_material_promoter_buys(days_lookback=7)
            except Exception as e:
                logger.warning(f"Could not fetch insider trades: {e}")

        return DailyDashboard52High(
            as_of_date=dt_str,
            new_radar_signals=new_signals,
            watchlist_buy_triggers=triggered_watchlist,
            active_portfolio_status=portfolio,
            material_insider_trades=insider_trades,
            summary_notes=summary_notes,
        )

    def format_daily_briefing_markdown(self, dashboard: DailyDashboard52High) -> str:
        """Format the DailyDashboard52High payload into an executive Markdown briefing."""
        md: List[str] = [
            f"# 🚀 QuantCopilot: 52-Week High Breakout Briefing ({dashboard.as_of_date})\n",
            "> **Strategy**: Institutional Breakout Accumulation (IBA) & Stage 2 Growth\n",
            "### 📌 Executive Summary",
        ]
        for note in dashboard.summary_notes:
            md.append(f"- {note}")
        md.append("")

        # 1. Stage 2 Watchlist Buy Triggers
        md.append("## 1. 🔥 Stage 2 Buy Triggers (Actionable Today)")
        if dashboard.watchlist_buy_triggers:
            md.append("| Symbol | Breakout Date | Trigger Price | Pivot High | Initial SL | Target 1 (+15%) | Target 2 (+30%) |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for w in dashboard.watchlist_buy_triggers:
                md.append(
                    f"| **{w.symbol}** | {w.breakout_date} | **₹{w.trigger_price or 0:.2f}** | "
                    f"₹{w.pivot_high:.2f} | ₹{w.initial_sl:.2f} | ₹{w.target_1_15pct:.2f} | ₹{w.target_2_30pct:.2f} |"
                )
        else:
            md.append("*No watchlist stocks triggered buy confirmations today.*")
        md.append("")

        # 2. Fresh Breakout Radar Signals
        md.append("## 2. 📡 Fresh Breakout Radar Candidates (Under Review)")
        if dashboard.new_radar_signals:
            md.append("| Symbol | Close Price | 52W High | Vol Expansion | Base Duration | Base Depth | Trailing SL | T1 (+15%) |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for s in dashboard.new_radar_signals:
                md.append(
                    f"| **{s.symbol}** | ₹{s.breakout_price:.2f} | ₹{s.high_52w:.2f} | "
                    f"**{s.volume_ratio:.2f}x** | {s.base_metrics.base_duration_days}d | "
                    f"-{s.base_metrics.base_depth_pct:.1f}% | ₹{s.initial_sl:.2f} | ₹{s.target_1_15pct:.2f} |"
                )
        else:
            md.append("*No fresh breakout candidates passed the 4-layer funnel today.*")
        md.append("")

        # 3. Active Portfolio Sentinel
        md.append("## 3. 🛡️ Active Holdings Sentinel (Trailing 20 EMA)")
        if dashboard.active_portfolio_status:
            md.append("| Symbol | Entry Date | Entry Px | Current Px | Unrealized PnL | Trailing SL | Status Badge |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            badge_icons = {
                HighStockStatusBadge.SAFE: "🟢 SAFE",
                HighStockStatusBadge.TIGHTENING: "🟡 TIGHTENING",
                HighStockStatusBadge.RADAR_ALERT: "🟠 RADAR ALERT",
                HighStockStatusBadge.DECISION_REQD: "🔴 DECISION REQD",
                HighStockStatusBadge.TARGET_1_HIT: "🎯 TARGET 1 HIT",
                HighStockStatusBadge.TARGET_2_HIT: "🏆 TARGET 2 HIT",
            }
            for p in dashboard.active_portfolio_status:
                badge_str = badge_icons.get(p.status_badge, p.status_badge.value)
                pnl_color = "+" if p.unrealized_pnl_pct >= 0 else ""
                md.append(
                    f"| **{p.symbol}** | {p.entry_date} | ₹{p.entry_price:.2f} | ₹{p.current_price:.2f} | "
                    f"**{pnl_color}{p.unrealized_pnl_pct:.2f}%** | ₹{p.trailing_sl:.2f} | {badge_str} |"
                )
        else:
            md.append("*No active holdings currently in 52W High portfolio.*")
        md.append("")

        # 4. Insider Activity
        if dashboard.material_insider_trades:
            md.append("## 4. 💼 Material Promoter Buying (SEBI PIT >= ₹1 Cr)")
            md.append("| Symbol | Filing Date | Acquirer | Value (INR) | Mode |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for t in dashboard.material_insider_trades:
                md.append(
                    f"| **{t.symbol}** | {t.filing_date} | {t.acquirer_name} | "
                    f"₹{t.value_inr/1e7:.2f} Cr | {t.acquisition_mode} |"
                )
            md.append("")

        return "\n".join(md)

    # -------------------------------------------------------------------------
    # MODULAR ACTIONS
    # -------------------------------------------------------------------------

    def scan_radar_candidates(
        self,
        candidate_symbols: Optional[List[str]] = None,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[BreakoutSignal], str]:
        """Scan candidate symbols for 52-Week High breakouts without modifying state."""
        signals = self.scanner.run_funnel_scan(candidate_symbols=candidate_symbols, as_of_date=as_of_date)
        dt_str = as_of_date or self._today_ist(self.tz)
        md = [
            f"# 52-Week High Breakout Radar ({dt_str})",
            f"Evaluated {len(candidate_symbols) if candidate_symbols else 'Nifty 500'} candidate symbols.\n",
        ]
        if signals:
            md.append("| Symbol | Close Price | 52W High | Volume Ratio | Base Depth | Trailing SL | T1 (+15%) | T2 (+30%) |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for s in signals:
                md.append(
                    f"| **{s.symbol}** | ₹{s.breakout_price:.2f} | ₹{s.high_52w:.2f} | "
                    f"**{s.volume_ratio:.2f}x** | -{s.base_metrics.base_depth_pct:.1f}% | "
                    f"₹{s.initial_sl:.2f} | ₹{s.target_1_15pct:.2f} | ₹{s.target_2_30pct:.2f} |"
                )
        else:
            md.append("*No stocks currently meet all 4 qualification layers.*")
        return signals, "\n".join(md)

    def get_portfolio_summary(
        self,
        current_prices_and_emas: Optional[Dict[str, Tuple[float, float]]] = None,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[HighPortfolioStock], str]:
        """Retrieve active portfolio holdings and format as Markdown table."""
        portfolio = self.tracker.get_portfolio()
        if not portfolio:
            return [], "# 52-Week High Portfolio\n\n*No active holdings.*"

        dt_str = as_of_date or self._today_ist(self.tz)
        price_map = current_prices_and_emas or self._fetch_latest_prices_and_emas(
            [p.symbol for p in portfolio], as_of_date=as_of_date
        )
        updated = self.tracker.update_portfolio_prices(price_map, as_of_date=dt_str)

        md = [
            f"# 52-Week High Active Portfolio ({dt_str})",
            "| Symbol | Entry Date | Qty | Entry Px | Current Px | Unrealized PnL | Trailing SL | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for p in updated:
            pnl_sign = "+" if p.unrealized_pnl_pct >= 0 else ""
            md.append(
                f"| **{p.symbol}** | {p.entry_date} | {p.remaining_quantity} | ₹{p.entry_price:.2f} | "
                f"₹{p.current_price:.2f} | **{pnl_sign}{p.unrealized_pnl_pct:.2f}%** | "
                f"₹{p.trailing_sl:.2f} | {p.status_badge.value} |"
            )
        return updated, "\n".join(md)

    def get_watchlist_summary(
        self,
        as_of_date: Optional[str] = None,
    ) -> Tuple[List[HighWatchlistStock], str]:
        """Check active watchlist stocks against latest prices."""
        watchlist = self.tracker.get_watchlist()
        if not watchlist:
            return [], "# 52-Week High Watchlist\n\n*Watchlist is currently empty.*"

        updated = self.scanner.check_watchlist(
            watchlist,
            get_daily_bars_fn=lambda s: self._get_recent_daily_bars(s, as_of_date=as_of_date, lookback_days=30),
        )
        self.tracker._save_watchlist(updated)

        dt_str = as_of_date or self._today_ist(self.tz)
        md = [
            f"# 52-Week High Watchlist ({dt_str})",
            "| Symbol | Added Date | Breakout Date | Pivot High | Initial SL | T1 (+15%) | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for w in updated:
            status = "🔥 BUY TRIGGERED" if w.is_buy_triggered else "⏳ Awaiting Follow-Through"
            md.append(
                f"| **{w.symbol}** | {w.added_date} | {w.breakout_date} | ₹{w.pivot_high:.2f} | "
                f"₹{w.initial_sl:.2f} | ₹{w.target_1_15pct:.2f} | {status} |"
            )
        return updated, "\n".join(md)

    def audit_single_symbol(
        self,
        symbol: str,
        df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Deep audit of a single symbol: technical breakout, base metrics, fundamentals, insider activity."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        if df is None:
            df = self._get_recent_daily_bars(clean_sym, lookback_days=400)

        tech = HighBreakoutScanner.calculate_technical_levels(df) if df is not None and len(df) >= 20 else {}
        base = HighBreakoutScanner.detect_consolidation_base(df) if df is not None and len(df) >= 20 else None
        exhaustion = HighBreakoutScanner.detect_exhaustion_climax(df, tech=tech) if df is not None and len(df) >= 20 else None

        audit = None
        try:
            audit = self.screener.audit_growth_company(clean_sym)
        except Exception as e:
            logger.warning(f"Could not fetch fundamentals for {clean_sym}: {e}")

        insider = self.insider.get_symbol_insider_activity(clean_sym)

        return {
            "symbol": clean_sym,
            "technical_levels": tech,
            "base_metrics": base.model_dump() if base else None,
            "exhaustion_metrics": exhaustion.model_dump() if exhaustion else None,
            "fundamental_audit": audit.model_dump() if audit else None,
            "insider_activity": insider.model_dump() if insider else None,
        }

    def add_to_watchlist(
        self,
        symbol: str,
        user_notes: Optional[str] = None,
        as_of_date: Optional[str] = None,
    ) -> HighWatchlistStock:
        """Add symbol to watchlist based on its latest breakout metrics."""
        clean_sym = symbol.upper()
        df = self._get_recent_daily_bars(clean_sym, as_of_date=as_of_date, lookback_days=400)
        signal = self.scanner.scan_candidate(
            clean_sym, df=df, as_of_date=as_of_date, skip_fundamental_audit=True
        )
        if signal is None:
            # Fallback signal from technical levels
            if df is None or len(df) < 20:
                raise ValueError(f"Insufficient candle history to add {clean_sym} to watchlist.")
            tech = HighBreakoutScanner.calculate_technical_levels(df)
            base = HighBreakoutScanner.detect_consolidation_base(df)
            px = tech["today_close"]
            signal = BreakoutSignal(
                symbol=clean_sym,
                breakout_date=as_of_date or self._today_ist(self.tz),
                breakout_price=px,
                high_52w=tech["high_52w"],
                today_high=tech["today_high"],
                today_low=tech["today_low"],
                today_volume=tech["today_volume"],
                avg_volume_20d=tech["vol_sma20"],
                volume_ratio=tech["volume_ratio"],
                initial_sl=round(px * 0.94, 2),
                trailing_20ema=tech["ema20"],
                target_1_15pct=round(px * 1.15, 2),
                target_2_30pct=round(px * 1.30, 2),
                base_metrics=base,
                exhaustion=HighBreakoutScanner.detect_exhaustion_climax(df, tech=tech),
                audit=FundamentalAudit(symbol=clean_sym, audit_date=as_of_date or self._today_ist(self.tz), passed_audit=True),
            )

        return self.tracker.add_to_watchlist(signal, user_notes=user_notes, added_date=as_of_date)

    def remove_from_watchlist(self, symbol: str) -> bool:
        """Remove a stock from the 52W High Watchlist."""
        return self.tracker.remove_from_watchlist(symbol)

    def record_buy(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        entry_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> HighPortfolioStock:
        """Record order execution into Tier 2 Active Portfolio."""
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
    ) -> Tuple[HighPortfolioStock, Optional[ClosedTradeLedger]]:
        """Record partial or full exit and archive to Tier 3 if completely sold."""
        return self.tracker.record_sell(
            symbol=symbol,
            sell_price=sell_price,
            quantity=quantity,
            reason=reason,
            sell_date=sell_date,
            notes=notes,
        )
