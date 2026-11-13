#!/usr/bin/env python3
"""CLI Runner for 52-Week High Breakout Strategy (Institutional Breakout Accumulation).

Usage:
    python scripts/run_52_high_scanner.py daily                 # Full evening dashboard
    python scripts/run_52_high_scanner.py portfolio             # Quick portfolio & trailing 20 EMA check
    python scripts/run_52_high_scanner.py watchlist             # Check watchlist Stage 2 buy triggers
    python scripts/run_52_high_scanner.py audit TRENT           # Deep-dive on single stock (base + growth + technicals)
    python scripts/run_52_high_scanner.py buy TRENT 50 7200.0 --notes "Confirmed breakout above pivot"
    python scripts/run_52_high_scanner.py sell TRENT 25 8280.0 TARGET_1 --notes "Booked 50% at +15%"
"""

import argparse
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.scanner.high_service import HighScannerService
from src.scanner.models import SellReason


def main():
    common_opts = argparse.ArgumentParser(add_help=False)
    common_opts.add_argument(
        "--offline",
        "--skip-prices",
        dest="offline",
        action="store_true",
        help="Skip live price auto-fetch from data providers",
    )

    parser = argparse.ArgumentParser(
        description="QuantCopilot: 52-Week High Strategy CLI & Dispatcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Daily Briefing
    p_daily = subparsers.add_parser(
        "daily",
        parents=[common_opts],
        help="Run full daily evening briefing ('Whats today for 52 High')",
    )
    p_daily.add_argument("--symbols", nargs="*", help="Optional specific list of candidate symbols to scan")
    p_daily.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 1b. Radar Scan
    p_radar = subparsers.add_parser(
        "radar",
        parents=[common_opts],
        help="Scan and audit 52-week high breakouts without altering portfolio state",
    )
    p_radar.add_argument("--symbols", nargs="*", help="Optional specific candidate symbols to filter and audit")
    p_radar.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 2. Portfolio Health
    p_port = subparsers.add_parser(
        "portfolio",
        parents=[common_opts],
        help="Quick view of Tier 2 active portfolio & trailing 20 EMA stops",
    )
    p_port.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 3. Watchlist
    p_watch = subparsers.add_parser(
        "watchlist",
        parents=[common_opts],
        help="Quick view of Tier 1 watchlist & Stage 2 buy triggers",
    )
    p_watch.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 4. Audit
    p_audit = subparsers.add_parser("audit", help="Run base, growth & technical audit on a single symbol")
    p_audit.add_argument("symbol", help="Stock ticker symbol (e.g. TRENT, BEL, HAL)")

    # 5. Buy
    p_buy = subparsers.add_parser("buy", help="Log order execution into Tier 2 Active Portfolio")
    p_buy.add_argument("symbol", help="Stock ticker symbol")
    p_buy.add_argument("quantity", type=int, help="Number of shares bought")
    p_buy.add_argument("price", type=float, help="Execution price per share (INR)")
    p_buy.add_argument("--date", help="Execution date (YYYY-MM-DD, default: today)")
    p_buy.add_argument("--notes", help="Discretionary thesis or user notes")

    # 6. Sell
    p_sell = subparsers.add_parser("sell", help="Log partial or full exit and archive to Tier 3 if full")
    p_sell.add_argument("symbol", help="Stock ticker symbol")
    p_sell.add_argument("quantity", type=int, help="Number of shares sold")
    p_sell.add_argument("price", type=float, help="Execution price per share (INR)")
    p_sell.add_argument(
        "reason",
        choices=["TARGET_1", "TARGET_2", "STOP_LOSS", "MANUAL"],
        help="Reason for exit",
    )
    p_sell.add_argument("--date", help="Execution date (YYYY-MM-DD, default: today)")
    p_sell.add_argument("--notes", help="Discretionary exit notes")

    args = parser.parse_args()
    service = HighScannerService()

    if args.command == "daily":
        cur_px = {} if args.offline else None
        db = service.get_daily_briefing(
            candidate_symbols=args.symbols,
            as_of_date=args.date,
            current_prices_and_emas=cur_px,
        )
        print(service.format_daily_briefing_markdown(db))

    elif args.command == "radar":
        _, md = service.scan_radar_candidates(candidate_symbols=args.symbols, as_of_date=args.date)
        print(md)

    elif args.command == "portfolio":
        cur_px = {} if args.offline else None
        _, md = service.get_portfolio_summary(current_prices_and_emas=cur_px, as_of_date=args.date)
        print(md)

    elif args.command == "watchlist":
        _, md = service.get_watchlist_summary(as_of_date=args.date)
        print(md)

    elif args.command == "audit":
        import json
        res = service.audit_single_symbol(args.symbol)
        print(json.dumps(res, indent=2))

    elif args.command == "buy":
        stock = service.record_buy(
            symbol=args.symbol,
            entry_price=args.price,
            quantity=args.quantity,
            entry_date=args.date,
            notes=args.notes,
        )
        print(
            f"✅ Recorded BUY for {stock.symbol}: {stock.remaining_quantity} shares @ ₹{stock.entry_price:.2f}. "
            f"Trailing SL: ₹{stock.trailing_sl:.2f}, T1 (+15%): ₹{stock.target_1_15pct:.2f}, T2 (+30%): ₹{stock.target_2_30pct:.2f}."
        )

    elif args.command == "sell":
        reason_enum = SellReason(args.reason)
        stock, ledger = service.record_sell(
            symbol=args.symbol,
            sell_price=args.price,
            quantity=args.quantity,
            reason=reason_enum,
            sell_date=args.date,
            notes=args.notes,
        )
        if ledger is not None:
            print(
                f"🏆 Trade CLOSED & Archived to Ledger for {ledger.symbol}: Total Realized PnL: ₹{ledger.net_realized_pnl_inr:+,.2f} "
                f"({ledger.net_return_pct:+.2f}%) over {ledger.holding_duration_days} days."
            )
        else:
            print(
                f"⚡ Partial EXIT logged for {stock.symbol}: Remaining: {stock.remaining_quantity} shares."
            )


if __name__ == "__main__":
    main()

