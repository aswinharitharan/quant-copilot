"""3-Tier Portfolio Tracker & Trailing Stop Sentinel for 52-Week High Strategy.

Manages the lifecycle across 3 storage tiers:
- Tier 1: data/watchlist_52_high.json (Watched breakout stocks waiting for Stage 2 confirmation)
- Tier 2: data/portfolio_52_high.json (Active holdings with dynamic trailing 20 EMA ratchet & targets)
- Tier 3: data/trade_history_52_high.json (Permanent closed trade audit ledger)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.scanner.models import (
    BreakoutSignal,
    ClosedTradeLedger,
    HighPortfolioStock,
    HighStockStatusBadge,
    HighWatchlistStock,
    SellReason,
    TradeSellRecord,
)

logger = logging.getLogger(__name__)


class HighPortfolioTracker:
    """Manager for 52-Week High Watchlist, Active Holdings, Trailing Stop Sentinel, and Ledger."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.watchlist_path = self.data_dir / "watchlist_52_high.json"
        self.portfolio_path = self.data_dir / "portfolio_52_high.json"
        self.ledger_path = self.data_dir / "trade_history_52_high.json"

        # Initialize JSON files if missing
        for path in (self.watchlist_path, self.portfolio_path, self.ledger_path):
            if not path.exists():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)

    # -------------------------------------------------------------------------
    # GENERIC JSON HELPERS
    # -------------------------------------------------------------------------

    def _read_json(self, path: Path) -> List[Dict]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
            return []

    def _write_json(self, path: Path, data: List[Dict]):
        temp_path = path.with_suffix(f".tmp_{os.getpid()}")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)

    # -------------------------------------------------------------------------
    # TIER 1: WATCHLIST MANAGEMENT
    # -------------------------------------------------------------------------

    def get_watchlist(self) -> List[HighWatchlistStock]:
        """Load active Tier 1 Watchlist for 52-Week High."""
        items = self._read_json(self.watchlist_path)
        return [HighWatchlistStock(**item) for item in items]

    def add_to_watchlist(
        self,
        signal: BreakoutSignal,
        user_notes: Optional[str] = None,
        added_date: Optional[str] = None,
    ) -> HighWatchlistStock:
        """Add a breakout candidate to Tier 1 Watchlist."""
        watchlist = self.get_watchlist()
        clean_sym = signal.symbol.upper()

        for stock in watchlist:
            if stock.symbol == clean_sym:
                if user_notes:
                    stock.add_note(f"User note update: {user_notes}")
                self._save_watchlist(watchlist)
                return stock

        dt_str = added_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        item = HighWatchlistStock(
            symbol=clean_sym,
            added_date=dt_str,
            breakout_date=signal.breakout_date,
            breakout_price=signal.breakout_price,
            pivot_high=signal.today_high,
            initial_sl=signal.initial_sl,
            trailing_20ema=signal.trailing_20ema,
            target_1_15pct=signal.target_1_15pct,
            target_2_30pct=signal.target_2_30pct,
            notes=user_notes or "",
        )

        auto_note = (
            f"Added to 52W High Watchlist. Breakout Close: ₹{signal.breakout_price:.2f}, Pivot High: ₹{signal.today_high:.2f}. "
            f"Volume Expansion: {signal.volume_ratio:.2f}x (Today: {signal.today_volume:,}, 20d SMA: {signal.avg_volume_20d:,.0f}). "
            f"Initial SL: ₹{signal.initial_sl:.2f}, Trailing 20 EMA: ₹{signal.trailing_20ema:.2f}, "
            f"T1 (+15%): ₹{signal.target_1_15pct:.2f}, T2 (+30%): ₹{signal.target_2_30pct:.2f}."
        )
        if signal.insider_activity:
            auto_note += f" Promoter Buying: ₹{signal.insider_activity.value_inr/1e7:.2f} Cr ({signal.insider_activity.acquirer_name})."
        if user_notes:
            auto_note += f" User thesis: '{user_notes}'"

        item.add_note(auto_note)
        watchlist.append(item)
        self._save_watchlist(watchlist)
        return item

    def remove_from_watchlist(self, symbol: str) -> bool:
        """Remove symbol from watchlist. Returns True if removed."""
        clean_sym = symbol.upper()
        watchlist = self.get_watchlist()
        filtered = [s for s in watchlist if s.symbol != clean_sym]
        if len(filtered) != len(watchlist):
            self._save_watchlist(filtered)
            return True
        return False

    def _save_watchlist(self, watchlist: List[HighWatchlistStock]):
        self._write_json(self.watchlist_path, [s.model_dump() for s in watchlist])

    # -------------------------------------------------------------------------
    # TIER 2: ACTIVE PORTFOLIO & TRAILING STOP SENTINEL
    # -------------------------------------------------------------------------

    def get_portfolio(self) -> List[HighPortfolioStock]:
        """Load active Tier 2 Portfolio for 52-Week High."""
        items = self._read_json(self.portfolio_path)
        return [HighPortfolioStock(**item) for item in items]

    def record_buy(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        entry_date: Optional[str] = None,
        notes: Optional[str] = None,
        initial_sl: Optional[float] = None,
        trailing_20ema: Optional[float] = None,
        target_1_15pct: Optional[float] = None,
        target_2_30pct: Optional[float] = None,
    ) -> HighPortfolioStock:
        """Register a buy into Tier 2 Active Portfolio for 52W High."""
        clean_sym = symbol.upper()
        dt_str = entry_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        watchlist = self.get_watchlist()

        matched_watch = next((s for s in watchlist if s.symbol == clean_sym), None)

        init_sl = initial_sl or (matched_watch.initial_sl if matched_watch else round(entry_price * 0.94, 2))
        trail_ema = trailing_20ema or (matched_watch.trailing_20ema if matched_watch else init_sl)
        t1 = target_1_15pct or (matched_watch.target_1_15pct if matched_watch else round(entry_price * 1.15, 2))
        t2 = target_2_30pct or (matched_watch.target_2_30pct if matched_watch else round(entry_price * 1.30, 2))

        # Dynamic trailing SL floor starts at max(init_sl, trail_ema)
        start_trail_sl = max(init_sl, trail_ema)

        item = HighPortfolioStock(
            symbol=clean_sym,
            entry_date=dt_str,
            entry_price=entry_price,
            total_quantity_bought=quantity,
            remaining_quantity=quantity,
            initial_sl=init_sl,
            highest_high_since_entry=entry_price,
            trailing_sl=start_trail_sl,
            target_1_15pct=t1,
            target_2_30pct=t2,
            current_price=entry_price,
            unrealized_pnl_pct=0.0,
            status_badge=HighStockStatusBadge.SAFE,
            notes=notes or "",
        )

        if matched_watch and matched_watch.history_notes:
            item.history_notes.extend(matched_watch.history_notes)

        item.add_note(
            f"BOUGHT {quantity} shares @ ₹{entry_price:.2f} on {dt_str}. Initial SL: ₹{init_sl:.2f}, "
            f"Trailing SL: ₹{start_trail_sl:.2f}, T1 (+15%): ₹{t1:.2f}, T2 (+30%): ₹{t2:.2f}. {notes or ''}".strip()
        )

        if matched_watch:
            self.remove_from_watchlist(clean_sym)

        portfolio = self.get_portfolio()
        portfolio = [p for p in portfolio if p.symbol != clean_sym]
        portfolio.append(item)
        self._save_portfolio(portfolio)
        return item

    def update_portfolio_prices(
        self,
        price_and_ema_map: Dict[str, Tuple[float, float]],
        as_of_date: Optional[str] = None,
    ) -> List[HighPortfolioStock]:
        """Update active holdings with current market price and 20-day EMA.
        
        Args:
            price_and_ema_map: Dict mapping symbol -> (current_price, current_20ema)
            as_of_date: Optional date string
        """
        portfolio = self.get_portfolio()
        dt_str = as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for stock in portfolio:
            clean_sym = stock.symbol.upper()
            if clean_sym in price_and_ema_map:
                curr_px, curr_ema20 = price_and_ema_map[clean_sym]
                stock.current_price = curr_px
                stock.unrealized_pnl_pct = round(((curr_px - stock.entry_price) / stock.entry_price) * 100, 2)

                # Track highest high
                if curr_px > stock.highest_high_since_entry:
                    stock.highest_high_since_entry = curr_px

                # Trailing Ratchet: Only moves UP, never down
                new_trail = max(stock.trailing_sl, curr_ema20)
                if new_trail > stock.trailing_sl:
                    stock.add_note(
                        f"Ratcheted Trailing SL from ₹{stock.trailing_sl:.2f} to ₹{new_trail:.2f} on {dt_str}."
                    )
                    stock.trailing_sl = round(new_trail, 2)

                # Evaluate Status Badge
                # 1. Target 2 (+30%)
                if curr_px >= stock.target_2_30pct:
                    stock.status_badge = HighStockStatusBadge.TARGET_2_HIT
                    marker = f"TARGET 2 HIT (+30%) on {dt_str}"
                    if not any(marker in n for n in stock.history_notes):
                        stock.add_note(f"{marker} @ ₹{curr_px:.2f}. Recommend booking remaining profit.")
                # 2. Target 1 (+15%)
                elif curr_px >= stock.target_1_15pct:
                    stock.status_badge = HighStockStatusBadge.TARGET_1_HIT
                    marker = f"TARGET 1 HIT (+15%) on {dt_str}"
                    if not any(marker in n for n in stock.history_notes):
                        stock.add_note(f"{marker} @ ₹{curr_px:.2f}. Recommend booking 50% profit and moving SL to BE.")
                        # Move trailing SL to breakeven if not already higher
                        if stock.trailing_sl < stock.entry_price:
                            stock.trailing_sl = stock.entry_price
                            stock.add_note(f"Moved Trailing SL to Breakeven ₹{stock.entry_price:.2f}.")
                # 3. Trailing Stop Breach Check
                elif curr_px < stock.trailing_sl:
                    stock.consecutive_closes_below_trail += 1
                    if stock.consecutive_closes_below_trail >= 2 or curr_px < stock.initial_sl:
                        stock.status_badge = HighStockStatusBadge.DECISION_REQD
                        marker = f"DECISION REQD on {dt_str}"
                        if not any(marker in n for n in stock.history_notes):
                            stock.add_note(
                                f"{marker}: Closed below Trailing SL ₹{stock.trailing_sl:.2f} for "
                                f"{stock.consecutive_closes_below_trail} consecutive sessions. Recommend full exit."
                            )
                    else:
                        stock.status_badge = HighStockStatusBadge.RADAR_ALERT
                        marker = f"RADAR ALERT on {dt_str}"
                        if not any(marker in n for n in stock.history_notes):
                            stock.add_note(
                                f"{marker}: First close below Trailing SL ₹{stock.trailing_sl:.2f} (@ ₹{curr_px:.2f}). Prepare exit."
                            )
                elif curr_px <= (stock.trailing_sl * 1.02):
                    stock.status_badge = HighStockStatusBadge.TIGHTENING
                    stock.consecutive_closes_below_trail = 0
                else:
                    stock.status_badge = HighStockStatusBadge.SAFE
                    stock.consecutive_closes_below_trail = 0

        self._save_portfolio(portfolio)
        return portfolio

    def record_sell(
        self,
        symbol: str,
        sell_price: float,
        quantity: int,
        reason: SellReason,
        sell_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Tuple[HighPortfolioStock, Optional[ClosedTradeLedger]]:
        """Record partial or full sell of active holding."""
        clean_sym = symbol.upper()
        dt_str = sell_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        portfolio = self.get_portfolio()

        stock = next((p for p in portfolio if p.symbol == clean_sym), None)
        if not stock:
            raise ValueError(f"Symbol {clean_sym} not found in active portfolio.")

        if quantity > stock.remaining_quantity:
            raise ValueError(
                f"Cannot sell {quantity} shares; only {stock.remaining_quantity} remaining."
            )

        proceeds = round(sell_price * quantity, 2)
        realized_pnl = round((sell_price - stock.entry_price) * quantity, 2)
        realized_pct = round(((sell_price - stock.entry_price) / stock.entry_price) * 100, 2)

        sell_rec = TradeSellRecord(
            sell_date=dt_str,
            quantity=quantity,
            sell_price=sell_price,
            reason=reason,
            proceeds_inr=proceeds,
            realized_pnl_inr=realized_pnl,
            realized_pnl_pct=realized_pct,
            notes=notes or "",
        )

        stock.partial_sells.append(sell_rec)
        stock.remaining_quantity -= quantity
        stock.current_price = sell_price
        stock.unrealized_pnl_pct = round(((sell_price - stock.entry_price) / stock.entry_price) * 100, 2)

        stock.add_note(
            f"SOLD {quantity} shares @ ₹{sell_price:.2f} ({reason.value}) on {dt_str}. "
            f"Realized PnL: ₹{realized_pnl:+,.2f} ({realized_pct:+.1f}%). Remaining: {stock.remaining_quantity} shares. {notes or ''}".strip()
        )

        ledger_entry: Optional[ClosedTradeLedger] = None

        if stock.remaining_quantity == 0:
            # Completely exited -> Archive to Tier 3 Ledger
            total_proceeds = sum(s.proceeds_inr for s in stock.partial_sells)
            total_invested = round(stock.entry_price * stock.total_quantity_bought, 2)
            net_pnl = sum(s.realized_pnl_inr for s in stock.partial_sells)
            net_ret_pct = round((net_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0

            try:
                d1 = datetime.strptime(stock.entry_date, "%Y-%m-%d")
                d2 = datetime.strptime(dt_str, "%Y-%m-%d")
                duration = max(1, (d2 - d1).days)
            except Exception:
                duration = 1

            ledger_entry = ClosedTradeLedger(
                symbol=clean_sym,
                entry_date=stock.entry_date,
                entry_price=stock.entry_price,
                total_quantity=stock.total_quantity_bought,
                total_invested_inr=total_invested,
                sells=stock.partial_sells,
                final_exit_date=dt_str,
                total_proceeds_inr=total_proceeds,
                net_realized_pnl_inr=net_pnl,
                net_return_pct=net_ret_pct,
                holding_duration_days=duration,
                notes=stock.notes,
                history_notes=stock.history_notes,
            )

            # Save to ledger
            ledger = self.get_closed_trades()
            ledger.append(ledger_entry)
            self._write_json(self.ledger_path, [l.model_dump() for l in ledger])

            # Remove from portfolio
            portfolio = [p for p in portfolio if p.symbol != clean_sym]
            self._save_portfolio(portfolio)
            return stock, ledger_entry

        self._save_portfolio(portfolio)
        return stock, None

    def get_closed_trades(self) -> List[ClosedTradeLedger]:
        """Load permanent Tier 3 Closed Trade Ledger."""
        items = self._read_json(self.ledger_path)
        return [ClosedTradeLedger(**item) for item in items]

    def _save_portfolio(self, portfolio: List[HighPortfolioStock]):
        self._write_json(self.portfolio_path, [p.model_dump() for p in portfolio])

