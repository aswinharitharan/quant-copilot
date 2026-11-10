"""3-Tier Portfolio Tracker & Daily Sentinel for 52-Week Low Strategy.

Manages the lifecycle across 3 storage tiers:
- Tier 1: data/watchlist_52_low.json (Watched stocks waiting for buy trigger)
- Tier 2: data/portfolio_52_low.json (Active holdings with soft stop & targets)
- Tier 3: data/trade_history_52_low.json (Permanent closed trade audit ledger)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from src.scanner.models import (
    CapitulationSignal,
    ClosedTradeLedger,
    PortfolioStock,
    SellReason,
    StockStatusBadge,
    TradeSellRecord,
    WatchlistStock,
)

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Manager for Watchlist, Active Holdings, Risk Sentinel, and Closed Trade Ledger."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.watchlist_path = self.data_dir / "watchlist_52_low.json"
        self.portfolio_path = self.data_dir / "portfolio_52_low.json"
        self.ledger_path = self.data_dir / "trade_history_52_low.json"

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

    def get_watchlist(self) -> List[WatchlistStock]:
        """Load active Tier 1 Watchlist."""
        items = self._read_json(self.watchlist_path)
        return [WatchlistStock(**item) for item in items]

    def add_to_watchlist(
        self,
        signal: CapitulationSignal,
        user_notes: Optional[str] = None,
        added_date: Optional[str] = None,
    ) -> WatchlistStock:
        """Add a candidate signal to Tier 1 Watchlist with initial context notes."""
        watchlist = self.get_watchlist()
        clean_sym = signal.symbol.upper()

        # Check if already present
        for stock in watchlist:
            if stock.symbol == clean_sym:
                if user_notes:
                    stock.add_note(f"User note update: {user_notes}")
                self._save_watchlist(watchlist)
                return stock

        dt_str = added_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        item = WatchlistStock(
            symbol=clean_sym,
            added_date=dt_str,
            capitulation_date=signal.capitulation_date,
            capitulation_low=signal.low_price,
            capitulation_high=signal.high_price,
            target_1_20ema=signal.target_1_20ema,
            target_2_50ema=signal.target_2_50ema,
            notes=user_notes or "",
        )

        # Build initial auto context note
        auto_note = (
            f"Added to Watchlist. Capitulation Low: ₹{signal.low_price:.2f}, High: ₹{signal.high_price:.2f}. "
            f"Volume Anomaly: {signal.volume_ratio:.2f}x (Today: {signal.today_volume:,}, 20d SMA: {signal.avg_volume_20d:,.0f}). "
            f"Targets: T1 (20 EMA)=₹{signal.target_1_20ema:.2f}, T2 (50 EMA)=₹{signal.target_2_50ema:.2f}."
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

    def handle_cascading_low(
        self,
        symbol: str,
        new_low: float,
        new_high: float,
        new_vol_ratio: float,
        new_date: str,
        new_target_1: float,
        new_target_2: float,
    ) -> Optional[WatchlistStock]:
        """Reset baseline when a watched stock experiences another high-volume capitulation cascade."""
        clean_sym = symbol.upper()
        watchlist = self.get_watchlist()

        for stock in watchlist:
            if stock.symbol == clean_sym:
                old_low = stock.capitulation_low
                stock.capitulation_date = new_date
                stock.capitulation_low = new_low
                stock.capitulation_high = new_high
                stock.target_1_20ema = new_target_1
                stock.target_2_50ema = new_target_2
                stock.is_buy_triggered = False  # Reset trigger if previously set

                stock.add_note(
                    f"Cascading Capitulation on {new_date}: Reset support low from ₹{old_low:.2f} to ₹{new_low:.2f} "
                    f"on {new_vol_ratio:.2f}x volume anomaly. New High: ₹{new_high:.2f}, T1: ₹{new_target_1:.2f}, T2: ₹{new_target_2:.2f}."
                )
                self._save_watchlist(watchlist)
                return stock

        return None

    def _save_watchlist(self, watchlist: List[WatchlistStock]):
        self._write_json(self.watchlist_path, [s.model_dump() for s in watchlist])

    # -------------------------------------------------------------------------
    # TIER 2: ACTIVE PORTFOLIO MANAGEMENT
    # -------------------------------------------------------------------------

    def get_portfolio(self) -> List[PortfolioStock]:
        """Load active Tier 2 Portfolio."""
        items = self._read_json(self.portfolio_path)
        return [PortfolioStock(**item) for item in items]

    def record_buy(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        entry_date: Optional[str] = None,
        notes: Optional[str] = None,
        capitulation_low: Optional[float] = None,
        target_1_20ema: Optional[float] = None,
        target_2_50ema: Optional[float] = None,
    ) -> PortfolioStock:
        """Register a buy into Tier 2 Active Portfolio.
        
        If the stock is in the Watchlist, pulls its capitulation levels and removes it from Watchlist.
        """
        clean_sym = symbol.upper()
        dt_str = entry_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        watchlist = self.get_watchlist()

        # Check if in watchlist
        matched_watch = next((s for s in watchlist if s.symbol == clean_sym), None)

        c_low = capitulation_low or (matched_watch.capitulation_low if matched_watch else entry_price * 0.95)
        t1 = target_1_20ema or (matched_watch.target_1_20ema if matched_watch else entry_price * 1.10)
        t2 = target_2_50ema or (matched_watch.target_2_50ema if matched_watch else entry_price * 1.20)

        # Dist from SL at entry
        dist_sl = round((entry_price - c_low) / c_low * 100, 2) if c_low > 0 else 0.0

        item = PortfolioStock(
            symbol=clean_sym,
            entry_date=dt_str,
            entry_price=entry_price,
            total_quantity_bought=quantity,
            remaining_quantity=quantity,
            capitulation_low=c_low,
            target_1_20ema=t1,
            target_2_50ema=t2,
            current_price=entry_price,
            dist_from_sl_pct=dist_sl,
            unrealized_pnl_pct=0.0,
            status_badge=StockStatusBadge.SAFE,
            notes=notes or "",
        )

        # Inherit notes from watchlist if available
        if matched_watch and matched_watch.history_notes:
            item.history_notes.extend(matched_watch.history_notes)

        item.add_note(
            f"BOUGHT {quantity} shares @ ₹{entry_price:.2f} on {dt_str}. Soft Stop: ₹{c_low:.2f} (-{dist_sl:.1f}%), "
            f"T1: ₹{t1:.2f}, T2: ₹{t2:.2f}. {notes or ''}".strip()
        )

        # Remove from watchlist
        if matched_watch:
            self.remove_from_watchlist(clean_sym)

        portfolio = self.get_portfolio()
        # If already exists, replace or append
        portfolio = [p for p in portfolio if p.symbol != clean_sym]
        portfolio.append(item)
        self._save_portfolio(portfolio)
        return item

    def record_partial_sell(
        self,
        symbol: str,
        sell_price: float,
        quantity: int,
        reason: SellReason,
        sell_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Tuple[PortfolioStock, Optional[ClosedTradeLedger]]:
        """Record partial or full sell of active holding.
        
        When remaining_quantity reaches 0, automatically archives the trade into Tier 3.
        Returns:
            Tuple of (updated_portfolio_stock, archived_ledger_record or None)
        """
        clean_sym = symbol.upper()
        dt_str = sell_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        portfolio = self.get_portfolio()

        stock = next((p for p in portfolio if p.symbol == clean_sym), None)
        if stock is None:
            raise ValueError(f"Stock '{clean_sym}' not found in active portfolio.")

        if quantity > stock.remaining_quantity:
            raise ValueError(f"Cannot sell {quantity} shares; only {stock.remaining_quantity} remaining.")

        proceeds = round(sell_price * quantity, 2)
        cost_basis = round(stock.entry_price * quantity, 2)
        realized_pnl = round(proceeds - cost_basis, 2)
        realized_pnl_pct = round((sell_price - stock.entry_price) / stock.entry_price * 100, 2)

        sell_rec = TradeSellRecord(
            sell_date=dt_str,
            quantity=quantity,
            sell_price=sell_price,
            reason=reason,
            proceeds_inr=proceeds,
            realized_pnl_inr=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            notes=notes or "",
        )

        stock.partial_sells.append(sell_rec)
        stock.remaining_quantity -= quantity
        stock.add_note(
            f"SOLD {quantity} shares @ ₹{sell_price:.2f} ({reason.value}) on {dt_str}. "
            f"Realized PnL: ₹{realized_pnl:,.2f} ({realized_pnl_pct:+.2f}%). Remaining: {stock.remaining_quantity}."
        )

        archived_ledger: Optional[ClosedTradeLedger] = None

        if stock.remaining_quantity == 0:
            # Full position closed -> Archive to Tier 3
            archived_ledger = self._archive_trade(stock, final_exit_date=dt_str)
            portfolio = [p for p in portfolio if p.symbol != clean_sym]
        else:
            # Update remaining holding
            for i, p in enumerate(portfolio):
                if p.symbol == clean_sym:
                    portfolio[i] = stock
                    break

        self._save_portfolio(portfolio)
        return stock, archived_ledger

    def _archive_trade(self, stock: PortfolioStock, final_exit_date: str) -> ClosedTradeLedger:
        """Move completed trade into Tier 3 Closed Trade Ledger."""
        total_invested = round(stock.entry_price * stock.total_quantity_bought, 2)
        total_proceeds = round(sum(s.proceeds_inr for s in stock.partial_sells), 2)
        net_realized_pnl = round(total_proceeds - total_invested, 2)
        net_return_pct = round(net_realized_pnl / total_invested * 100, 2) if total_invested > 0 else 0.0

        try:
            d_entry = datetime.strptime(stock.entry_date[:10], "%Y-%m-%d")
            d_exit = datetime.strptime(final_exit_date[:10], "%Y-%m-%d")
            duration_days = max(1, (d_exit - d_entry).days)
        except Exception:
            duration_days = 1

        ledger_entry = ClosedTradeLedger(
            symbol=stock.symbol,
            entry_date=stock.entry_date,
            entry_price=stock.entry_price,
            total_quantity=stock.total_quantity_bought,
            total_invested_inr=total_invested,
            sells=stock.partial_sells,
            final_exit_date=final_exit_date,
            total_proceeds_inr=total_proceeds,
            net_realized_pnl_inr=net_realized_pnl,
            net_return_pct=net_return_pct,
            holding_duration_days=duration_days,
            notes=stock.notes,
            history_notes=stock.history_notes,
        )

        ledger_entry.history_notes.append(
            f"[{final_exit_date}] Position fully closed. Net PnL: ₹{net_realized_pnl:,.2f} ({net_return_pct:+.2f}%) "
            f"over {duration_days} days."
        )

        ledger = self.get_trade_ledger()
        ledger.append(ledger_entry)
        self._save_ledger(ledger)
        return ledger_entry

    def _save_portfolio(self, portfolio: List[PortfolioStock]):
        self._write_json(self.portfolio_path, [p.model_dump() for p in portfolio])

    # -------------------------------------------------------------------------
    # TIER 3: CLOSED TRADE LEDGER
    # -------------------------------------------------------------------------

    def get_trade_ledger(self) -> List[ClosedTradeLedger]:
        """Load Tier 3 permanent closed trade ledger."""
        items = self._read_json(self.ledger_path)
        return [ClosedTradeLedger(**item) for item in items]

    def _save_ledger(self, ledger: List[ClosedTradeLedger]):
        self._write_json(self.ledger_path, [l.model_dump() for l in ledger])

    # -------------------------------------------------------------------------
    # DAILY RISK SENTINEL & STATUS BADGES
    # -------------------------------------------------------------------------

    def evaluate_portfolio_health(self, current_prices: Dict[str, float]) -> List[PortfolioStock]:
        """Evaluate active holdings against Soft Stop-Loss and Targets.
        
        Assigns Badges:
        - TARGET_2_HIT: Current Price >= 50 EMA
        - TARGET_1_HIT: Current Price >= 20 EMA
        - DECISION_REQD: Current Price < Capitulation Low
        - RADAR_ALERT: Current Price within 1.5% above Capitulation Low
        - SAFE: Current Price > 3.0% above Capitulation Low
        """
        portfolio = self.get_portfolio()
        updated_portfolio: List[PortfolioStock] = []

        for stock in portfolio:
            sym = stock.symbol
            price = current_prices.get(sym)
            if price is None:
                updated_portfolio.append(stock)
                continue

            stock.current_price = price
            stock.unrealized_pnl_pct = round((price - stock.entry_price) / stock.entry_price * 100, 2)

            # Distance from Soft Stop (Capitulation Low)
            c_low = stock.capitulation_low
            dist_from_sl = round((price - c_low) / c_low * 100, 2) if c_low > 0 else 0.0
            stock.dist_from_sl_pct = dist_from_sl

            prev_badge = stock.status_badge

            # Evaluate badge priority:
            if price >= stock.target_2_50ema:
                stock.status_badge = StockStatusBadge.TARGET_2_HIT
            elif price >= stock.target_1_20ema:
                stock.status_badge = StockStatusBadge.TARGET_1_HIT
            elif price < c_low:
                stock.status_badge = StockStatusBadge.DECISION_REQD
            elif dist_from_sl <= 1.5:
                stock.status_badge = StockStatusBadge.RADAR_ALERT
            else:
                stock.status_badge = StockStatusBadge.SAFE

            # Log change in status if badge changed
            if stock.status_badge != prev_badge:
                stock.add_note(
                    f"Sentinel Status changed from {prev_badge.value} to {stock.status_badge.value} @ ₹{price:.2f} "
                    f"(Dist from SL: {dist_from_sl:+.2f}%, Unrealized PnL: {stock.unrealized_pnl_pct:+.2f}%)."
                )

            updated_portfolio.append(stock)

        self._save_portfolio(updated_portfolio)
        return updated_portfolio

