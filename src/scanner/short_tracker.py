"""Storage & Watchlist Tracker for 52-Week High Exhaustion Short Strategy (Phase 1).

Manages the lifecycle across 2 storage tiers:
- Tier 1: data/watchlist_52_short.json (Stocks that printed Day 1 Climax traps awaiting Day 2 trigger)
- Tier 3: data/trade_history_52_short.json (Permanent audit ledger of realized Intraday MIS trades)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from src.scanner.models import (
    ExhaustionShortSignal,
    ShortExitReason,
    ShortSignalStage,
    ShortTradeRecord,
    ShortWatchlistStock,
)

logger = logging.getLogger(__name__)


class ShortPortfolioTracker:
    """Manager for Day 1 Short Watchlist and Completed Intraday Trade History."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.watchlist_path = self.data_dir / "watchlist_52_short.json"
        self.ledger_path = self.data_dir / "trade_history_52_short.json"

        for path in (self.watchlist_path, self.ledger_path):
            if not path.exists():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)

    def _read_json(self, path: Path) -> List[Dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Error reading {path}: {e}")
            return []

    def _write_json(self, path: Path, data: List[Dict]):
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(path)
        except Exception as e:
            logger.error(f"Error writing {path}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise

    # -------------------------------------------------------------------------
    # TIER 1: SHORT WATCHLIST
    # -------------------------------------------------------------------------

    def get_watchlist(self) -> List[ShortWatchlistStock]:
        """Load all stocks from data/watchlist_52_short.json."""
        raw = self._read_json(self.watchlist_path)
        return [ShortWatchlistStock(**item) for item in raw]

    def _save_watchlist(self, items: List[ShortWatchlistStock]):
        raw = [item.model_dump() for item in items]
        self._write_json(self.watchlist_path, raw)

    def add_to_watchlist(
        self,
        signal_or_symbol: Union[ExhaustionShortSignal, str],
        climax_low: Optional[float] = None,
        climax_high: Optional[float] = None,
        climax_date: Optional[str] = None,
        added_date: Optional[str] = None,
        user_notes: Optional[str] = None,
    ) -> ShortWatchlistStock:
        """Add or update a stock in the Day 1 Short Watchlist."""
        watchlist = self.get_watchlist()

        if isinstance(signal_or_symbol, ExhaustionShortSignal):
            sig = signal_or_symbol
            clean_sym = sig.symbol.upper()
            c_low = sig.climax_low
            c_high = sig.climax_high
            c_date = sig.climax_date
            t1 = sig.target_1_mis
            t2 = sig.target_2_mis
            v_ratio = sig.volume_ratio
            u_wick = sig.upper_wick_pct
        else:
            clean_sym = signal_or_symbol.upper()
            if climax_low is None or climax_high is None:
                raise ValueError("Must provide climax_low and climax_high when adding by string symbol.")
            c_low = float(climax_low)
            c_high = float(climax_high)
            c_date = climax_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            t1 = round(c_low * 0.98, 2)
            t2 = round(c_low * 0.96, 2)
            v_ratio = 3.0
            u_wick = 50.0

        for stock in watchlist:
            if stock.symbol == clean_sym:
                stock.climax_date = c_date
                stock.trigger_level_low = c_low
                stock.invalidation_level_high = c_high
                stock.target_1_mis = t1
                stock.target_2_mis = t2
                stock.status = ShortSignalStage.RADAR_CLIMAX
                stock.add_note(f"Updated Day 1 Climax Trap: Low=₹{c_low:.2f}, High=₹{c_high:.2f}")
                self._save_watchlist(watchlist)
                return stock

        dt_str = added_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        item = ShortWatchlistStock(
            symbol=clean_sym,
            added_date=dt_str,
            climax_date=c_date,
            trigger_level_low=c_low,
            invalidation_level_high=c_high,
            target_1_mis=t1,
            target_2_mis=t2,
            status=ShortSignalStage.RADAR_CLIMAX,
            notes=user_notes or "",
        )
        auto_note = (
            f"Added to Short Watchlist. Day 1 Climax Low (Sell Trigger): ₹{c_low:.2f}, High (Hard SL): ₹{c_high:.2f}. "
            f"Vol Ratio: {v_ratio:.2f}x, Upper Wick: {u_wick:.1f}%. Targets: T1 (-2%)=₹{t1:.2f}, T2 (-4%)=₹{t2:.2f}."
        )
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

    def update_stock_status(
        self,
        symbol: str,
        new_status: ShortSignalStage,
        note: str,
    ) -> Optional[ShortWatchlistStock]:
        """Update status of a watchlist stock (e.g. TRIGGERED_MIS, INVALIDATED)."""
        clean_sym = symbol.upper()
        watchlist = self.get_watchlist()
        for stock in watchlist:
            if stock.symbol == clean_sym:
                stock.status = new_status
                stock.add_note(note)
                self._save_watchlist(watchlist)
                return stock
        return None

    def rollover_to_day3_continuation(
        self,
        symbol: str,
        day2_low: float,
        day2_high: float,
        day2_close: float,
        note: Optional[str] = None,
    ) -> Optional[ShortWatchlistStock]:
        """Rollover a stock that broke down on Day 2 into Day 3 Continuation Watchlist."""
        clean_sym = symbol.upper()
        watchlist = self.get_watchlist()
        for stock in watchlist:
            if stock.symbol == clean_sym:
                stock.status = ShortSignalStage.RADAR_DAY3_CONTINUATION
                stock.is_continuation = True
                stock.day1_low = stock.trigger_level_low
                stock.day2_low = day2_low
                stock.day2_high = day2_high
                stock.day2_close = day2_close
                # Day 3 trigger is Day 2 Low!
                stock.trigger_level_low = day2_low
                stock.invalidation_level_high = day2_high
                stock.target_1_mis = round(day2_low * 0.98, 2)
                stock.target_2_mis = round(day2_low * 0.96, 2)
                msg = note or f"Rolled over to Day 3 Continuation Short: New trigger below Day 2 Low ₹{day2_low:.2f}, Invalidation ₹{day2_high:.2f}."
                stock.add_note(msg)
                self._save_watchlist(watchlist)
                return stock
        return None

    # -------------------------------------------------------------------------
    # TIER 3: TRADE HISTORY LEDGER
    # -------------------------------------------------------------------------

    def get_ledger(self) -> List[ShortTradeRecord]:
        """Load all closed trades from data/trade_history_52_short.json."""
        raw = self._read_json(self.ledger_path)
        return [ShortTradeRecord(**item) for item in raw]

    def record_completed_short(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        exit_reason: ShortExitReason,
        trade_date: Optional[str] = None,
        entry_time: str = "09:30",
        exit_time: str = "15:10",
        notes: Optional[str] = "",
    ) -> ShortTradeRecord:
        """Record a completed Intraday MIS Short trade and clean up watchlist."""
        clean_sym = symbol.upper()
        t_date = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # In a short: PnL = (Entry Price - Exit Price) * Quantity
        realized_pnl = round((entry_price - exit_price) * quantity, 2)
        realized_pnl_pct = round(((entry_price - exit_price) / entry_price) * 100, 2)

        record = ShortTradeRecord(
            symbol=clean_sym,
            trade_date=t_date,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            exit_reason=exit_reason,
            realized_pnl_inr=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            notes=notes or "",
        )

        ledger = self.get_ledger()
        ledger.append(record)
        raw_ledger = [item.model_dump() for item in ledger]
        self._write_json(self.ledger_path, raw_ledger)

        # Remove from watchlist once realized
        self.remove_from_watchlist(clean_sym)
        return record

