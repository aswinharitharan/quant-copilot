#!/usr/bin/env python3
"""CLI Runner for 52-Week High Exhaustion Short Strategy (Phase 1: Intraday MIS).

Usage:
    python scripts/run_52_short_scanner.py daily                 # Full evening dashboard
    python scripts/run_52_short_scanner.py radar                 # Scan for Day 1 Climax Traps
    python scripts/run_52_short_scanner.py watchlist             # View Day 2 breakdown watchlist
    python scripts/run_52_short_scanner.py add HINDOILEXP 214.5 229.8 # Add Day 1 trap manually
    python scripts/run_52_short_scanner.py record HINDOILEXP 214.0 209.5 500 TARGET_1 # Record trade
"""

import argparse
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.scanner.models import ShortExitReason
from src.scanner.short_service import ShortScannerService


def main():
    parser = argparse.ArgumentParser(
        description="QuantCopilot: 52-Week High Exhaustion Short Strategy (Intraday MIS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Daily Briefing
    p_daily = subparsers.add_parser("daily", help="Run full daily briefing for 52W High Exhaustion Shorts")
    p_daily.add_argument("--symbols", nargs="*", help="Optional specific candidate symbols")
    p_daily.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 2. Radar Scan
    p_radar = subparsers.add_parser("radar", help="Scan for Day 1 Climax Traps without changing watchlist")
    p_radar.add_argument("--symbols", nargs="*", help="Optional candidate symbols")
    p_radar.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 3. Watchlist
    p_watch = subparsers.add_parser("watchlist", help="View Day 1 Climax traps awaiting Day 2 breakdown")

    # 4. Add to Watchlist
    p_add = subparsers.add_parser("add", help="Add or update a stock on the Day 1 Short Watchlist")
    p_add.add_argument("symbol", help="Stock ticker symbol")
    p_add.add_argument("low", type=float, help="Day 1 Climax Low (Sell Trigger)")
    p_add.add_argument("high", type=float, help="Day 1 Climax High (Hard Invalidation)")
    p_add.add_argument("--date", help="Climax date (YYYY-MM-DD)")
    p_add.add_argument("--notes", help="Optional notes")

    # 5. Record Completed Trade
    p_rec = subparsers.add_parser("record", help="Record a completed Intraday MIS Short trade to the permanent ledger")
    p_rec.add_argument("symbol", help="Stock ticker symbol")
    p_rec.add_argument("entry_price", type=float, help="Execution short entry price")
    p_rec.add_argument("exit_price", type=float, help="Covering buy price")
    p_rec.add_argument("quantity", type=int, help="Number of shares traded")
    p_rec.add_argument("reason", choices=[r.value for r in ShortExitReason], help="Exit reason")
    p_rec.add_argument("--date", help="Trade date (YYYY-MM-DD)")
    p_rec.add_argument("--notes", help="Trade notes")

    args = parser.parse_args()
    service = ShortScannerService()

    if args.command == "daily":
        print("🔻 Running 52-Week High Exhaustion Short Daily Scan...")
        db = service.get_daily_briefing(candidate_symbols=args.symbols, as_of_date=args.date)
        print("\n" + service.format_daily_briefing_markdown(db))

    elif args.command == "radar":
        print("📡 Scanning for Day 1 Climax Traps at 52-Week Highs...")
        _, summary = service.scan_radar_candidates(candidate_symbols=args.symbols, as_of_date=args.date)
        print("\n" + summary)

    elif args.command == "watchlist":
        _, summary = service.get_watchlist_summary()
        print("\n" + summary)

    elif args.command == "add":
        stock = service.tracker.add_to_watchlist(
            signal_or_symbol=args.symbol,
            climax_low=args.low,
            climax_high=args.high,
            climax_date=args.date,
            user_notes=args.notes,
        )
        print(f"✅ Added {stock.symbol} to Short Watchlist.")
        print(f"   Sell Trigger (Day 1 Low): ₹{stock.trigger_level_low:.2f}")
        print(f"   Hard Invalidation (Day 1 High): ₹{stock.invalidation_level_high:.2f}")
        print(f"   T1 (-2%): ₹{stock.target_1_mis:.2f} | T2 (-4%): ₹{stock.target_2_mis:.2f}")

    elif args.command == "record":
        reason_enum = ShortExitReason(args.reason)
        rec = service.tracker.record_completed_short(
            symbol=args.symbol,
            entry_price=args.entry_price,
            exit_price=args.exit_price,
            quantity=args.quantity,
            exit_reason=reason_enum,
            trade_date=args.date,
            notes=args.notes,
        )
        pnl_symbol = "+" if rec.realized_pnl_inr >= 0 else ""
        print(f"✅ Recorded Intraday MIS Short on {rec.symbol}:")
        print(f"   Sold: ₹{rec.entry_price:.2f} -> Covered: ₹{rec.exit_price:.2f} ({rec.quantity} shares)")
        print(f"   Net Realized PnL: {pnl_symbol}₹{rec.realized_pnl_inr:,.2f} ({pnl_symbol}{rec.realized_pnl_pct:.2f}%)")
        print(f"   Exit Reason: {rec.exit_reason.value}")


if __name__ == "__main__":
    main()

