#!/usr/bin/env python3
"""CLI Runner for 52-Week Low Capitulation Strategy.

Usage:
    python scripts/run_52_scanner.py daily                 # Full evening dashboard
    python scripts/run_52_scanner.py portfolio             # Quick portfolio health check
    python scripts/run_52_scanner.py watchlist             # Check watchlist buy triggers
    python scripts/run_52_scanner.py audit NESTLEIND       # Deep-dive on single stock
    python scripts/run_52_scanner.py buy NESTLEIND 100 2150.0 --notes "Reclaimed 5 EMA"
    python scripts/run_52_scanner.py sell NESTLEIND 50 2280.0 TARGET_1 --notes "Booked 50%"
"""

import argparse
import sys
from pathlib import Path

# Ensure root in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.scanner.models import SellReason
from src.scanner.service import ScannerService


def main():
    common_opts = argparse.ArgumentParser(add_help=False)
    common_opts.add_argument(
        "--offline",
        "--skip-prices",
        dest="offline",
        action="store_true",
        help="Skip live price auto-fetch from data providers and render 'price N/A'",
    )

    parser = argparse.ArgumentParser(
        description="QuantCopilot: 52-Week Low Strategy CLI & Dispatcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Daily Briefing
    p_daily = subparsers.add_parser(
        "daily",
        parents=[common_opts],
        help="Run full daily evening briefing ('Whats today for 52')",
    )
    p_daily.add_argument("--symbols", nargs="*", help="Optional specific list of candidate symbols to scan")
    p_daily.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 1b. Radar Scan (Only Discovery + Filter + Audit)
    p_radar = subparsers.add_parser(
        "radar",
        parents=[common_opts],
        help="Scan, filter and audit 52-week low stocks without checking portfolio",
    )
    p_radar.add_argument("--symbols", nargs="*", help="Optional specific candidate symbols to filter and audit")
    p_radar.add_argument("--date", help="Optional as-of date (YYYY-MM-DD)")

    # 2. Portfolio Health
    p_port = subparsers.add_parser(
        "portfolio",
        parents=[common_opts],
        help="Quick view of Tier 2 active portfolio & soft stop badges",
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
    p_audit = subparsers.add_parser("audit", help="Run fundamental & insider audit on a single symbol")
    p_audit.add_argument("symbol", help="Stock ticker symbol (e.g. NESTLEIND, TATACONSUM)")

    # 5. Buy
    p_buy = subparsers.add_parser("buy", help="Record a buy execution into Tier 2 Active Portfolio")
    p_buy.add_argument("symbol", help="Stock ticker symbol")
    p_buy.add_argument("quantity", type=int, help="Number of shares bought")
    p_buy.add_argument("price", type=float, help="Execution price per share")
    p_buy.add_argument("--date", help="Entry date (YYYY-MM-DD)")
    p_buy.add_argument("--notes", help="Entry rationale or notes")

    # 6. Sell
    p_sell = subparsers.add_parser("sell", help="Record a partial or full sale")
    p_sell.add_argument("symbol", help="Stock ticker symbol")
    p_sell.add_argument("quantity", type=int, help="Number of shares sold")
    p_sell.add_argument("price", type=float, help="Selling price per share")
    p_sell.add_argument(
        "reason",
        choices=["TARGET_1", "TARGET_2", "STOP_LOSS", "MANUAL"],
        help="Reason for booking sale",
    )
    p_sell.add_argument("--date", help="Selling date (YYYY-MM-DD)")
    p_sell.add_argument("--notes", help="Exit notes or rationale")

    args = parser.parse_args()
    service = ScannerService()

    if args.command == "daily":
        print("🔍 Running 52-Week Low Daily Funnel Scan...")
        current_prices = {} if getattr(args, "offline", False) else None
        dashboard = service.get_daily_briefing(
            candidate_symbols=args.symbols,
            as_of_date=args.date,
            current_prices=current_prices,
        )
        md = service.format_daily_briefing_markdown(dashboard)
        print("\n" + md)

    elif args.command == "radar":
        print("📡 Running 52-Week Low Radar (Discovery + Filter + Audit)...")
        _, summary = service.scan_radar_candidates(
            candidate_symbols=args.symbols,
            as_of_date=args.date,
        )
        print("\n" + summary)

    elif args.command == "portfolio":
        current_prices = {} if getattr(args, "offline", False) else None
        _, summary = service.get_portfolio_summary(current_prices=current_prices, as_of_date=args.date)
        print("\n" + summary)

    elif args.command == "watchlist":
        _, summary = service.get_watchlist_summary(as_of_date=args.date)
        print("\n" + summary)

    elif args.command == "audit":
        print(f"📊 Auditing {args.symbol}...")
        res = service.audit_single_symbol(args.symbol)
        audit = res["fundamental_audit"]
        insider = res["insider_activity"]

        print(f"\n--- Fundamental Audit: {audit.symbol} ---")
        print(f"Passed 5 Golden Rules: {'✅ YES' if audit.passed_audit else '❌ NO'}")
        if not audit.passed_audit:
            print("Failure Reasons:")
            for r in audit.failure_reasons:
                print(f"  - {r}")
        print(f"Market Cap: ₹{audit.market_cap_cr:,.0f} Cr" if audit.market_cap_cr else "Market Cap: N/A")
        print(f"D/E: {audit.debt_to_equity} | Int Coverage: {audit.interest_coverage}x | ROCE: {audit.roce_pct}%")
        print(f"Pledge: {audit.promoter_pledge_pct}% | Operating Cash Flow: ₹{audit.cfo_last_yr_cr} Cr")

        if insider:
            print(f"\n--- Insider Buying (SEBI PIT) ---")
            print(f"Acquirer: {insider.acquirer_name} ({insider.category})")
            print(f"Mode: {insider.acquisition_mode} | Value: ₹{insider.value_inr/1e7:.2f} Cr")
            print(f"Date: {insider.filing_date}")

    elif args.command == "buy":
        pos = service.record_buy(
            symbol=args.symbol,
            entry_price=args.price,
            quantity=args.quantity,
            entry_date=args.date,
            notes=args.notes,
        )
        print(f"\n✅ Registered {pos.total_quantity_bought} shares of {pos.symbol} @ ₹{pos.entry_price:.2f}.")
        print(f"Soft Stop SL: ₹{pos.capitulation_low:.2f} | T1: ₹{pos.target_1_20ema:.2f} | T2: ₹{pos.target_2_50ema:.2f}")

    elif args.command == "sell":
        stock, archived = service.record_sell(
            symbol=args.symbol,
            sell_price=args.price,
            quantity=args.quantity,
            reason=SellReason(args.reason),
            sell_date=args.date,
            notes=args.notes,
        )
        if archived:
            print(f"\n🏆 Position in {archived.symbol} fully closed & archived to Tier 3 Ledger!")
            print(f"Net Realized PnL: ₹{archived.net_realized_pnl_inr:,.2f} ({archived.net_return_pct:+.2f}%)")
            print(f"Holding Duration: {archived.holding_duration_days} days.")
        else:
            print(f"\n✅ Sold {args.quantity} shares of {stock.symbol} @ ₹{args.price:.2f}.")
            print(f"Remaining: {stock.remaining_quantity} shares.")


if __name__ == "__main__":
    main()

