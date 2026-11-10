"""Screener.in Fundamental Auditor for QuantCopilot 52-Week Strategy.

Scrapes and evaluates public financial metrics to enforce the 5 Golden Solvency Rules:
1. Promoter Pledge == 0%
2. Debt to Equity < 0.60
3. Interest Coverage Ratio > 3.5
4. Operating Cash Flow (CFO) > 0
5. ROCE >= 12%
"""

import json
import logging
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from src.scanner.models import FundamentalAudit

logger = logging.getLogger(__name__)


class ScreenerClient:
    """Client to scrape, cache, and audit fundamental solvency metrics from Screener.in."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, cache_dir: str = "data/cache", cache_ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_hours * 3600

    def _get_cache_path(self, symbol: str) -> Path:
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        return self.cache_dir / f"fundamentals_{clean_sym}.json"

    def _clean_num(self, val_str: Optional[str]) -> Optional[float]:
        """Convert raw formatted string (e.g. '₹33,196Cr.', '13.9%') into a float."""
        if not val_str:
            return None
        clean = re.sub(r"[^\d.-]", "", val_str)
        try:
            return float(clean)
        except (ValueError, TypeError):
            return None

    def fetch_html(self, symbol: str) -> str:
        """Fetch company HTML from Screener.in, trying consolidated first then standalone."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        headers = {"User-Agent": self.DEFAULT_USER_AGENT}

        urls = [
            f"https://www.screener.in/company/{clean_sym}/consolidated/",
            f"https://www.screener.in/company/{clean_sym}/",
        ]

        last_err = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    if resp.status == 200:
                        return resp.read().decode("utf-8")
            except Exception as e:
                last_err = e
                continue

        raise ConnectionError(f"Failed to fetch Screener.in data for {clean_sym}: {last_err}")

    def parse_html(self, symbol: str, html: str) -> FundamentalAudit:
        """Parse HTML string from Screener.in and construct FundamentalAudit."""
        soup = BeautifulSoup(html, "html.parser")
        audit_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Top ratios
        top_ratios: Dict[str, str] = {}
        for li in soup.select("#top-ratios li"):
            name_el = li.select_one(".name")
            val_el = li.select_one(".value")
            if name_el and val_el:
                top_ratios[name_el.get_text(strip=True)] = val_el.get_text(strip=True)

        mcap = self._clean_num(top_ratios.get("Market Cap"))
        price = self._clean_num(top_ratios.get("Current Price"))
        pe = self._clean_num(top_ratios.get("Stock P/E"))
        roce = self._clean_num(top_ratios.get("ROCE"))
        roe = self._clean_num(top_ratios.get("ROE"))

        # 2. Balance sheet: Equity Capital, Reserves, Borrowings
        equity = 0.0
        reserves = 0.0
        borrowings = 0.0
        bs = soup.select_one("#balance-sheet")
        if bs:
            for tr in bs.select("tr"):
                cells = [td.get_text(strip=True) for td in tr.select("td")]
                if cells:
                    name = cells[0].lower()
                    last_val = self._clean_num(cells[-1]) or 0.0
                    if "equity capital" in name:
                        equity = last_val
                    elif "reserves" in name:
                        reserves = last_val
                    elif "borrowings" in name:
                        borrowings = last_val

        net_worth = equity + reserves
        if net_worth > 0:
            debt_to_equity = round(borrowings / net_worth, 2)
        else:
            debt_to_equity = 999.0 if borrowings > 0 else 0.0

        # 3. P&L: Operating Profit, Interest
        op_profit = 0.0
        interest = 0.0
        pl = soup.select_one("#profit-loss")
        if pl:
            for tr in pl.select("tr"):
                cells = [td.get_text(strip=True) for td in tr.select("td")]
                if cells:
                    name = cells[0].lower()
                    last_val = self._clean_num(cells[-1]) or 0.0
                    if "operating profit" in name:
                        op_profit = last_val
                    elif "interest" in name:
                        interest = last_val

        if interest > 0:
            int_coverage = round(op_profit / interest, 2)
        elif interest == 0 and op_profit > 0:
            int_coverage = 999.0  # Zero interest / debt-free
        else:
            int_coverage = 0.0

        # 4. Cash Flow: Operating
        cfo: Optional[float] = None
        cf = soup.select_one("#cash-flow")
        if cf:
            for tr in cf.select("tr"):
                cells = [td.get_text(strip=True) for td in tr.select("td")]
                if cells and "operating" in cells[0].lower():
                    cfo = self._clean_num(cells[-1])
                    break

        # 5. Shareholding: Promoters, Pledge
        promoter_holding = 0.0
        pledge_pct = 0.0
        sh = soup.select_one("#shareholding")
        if sh:
            for tr in sh.select("tr"):
                cells = [td.get_text(strip=True) for td in tr.select("td")]
                if cells:
                    name = cells[0].lower()
                    val = self._clean_num(cells[-1]) or 0.0
                    if "promoter" in name and "pledg" not in name:
                        promoter_holding = val
                    elif "pledg" in name:
                        pledge_pct = val

        raw_audit = FundamentalAudit(
            symbol=symbol.upper(),
            audit_date=audit_date,
            market_cap_cr=mcap,
            current_price=price,
            pe_ratio=pe,
            roce_pct=roce,
            roe_pct=roe,
            debt_to_equity=debt_to_equity,
            interest_coverage=int_coverage,
            cfo_last_yr_cr=cfo,
            promoter_holding_pct=promoter_holding,
            promoter_pledge_pct=pledge_pct,
        )

        return self.evaluate_rules(raw_audit)

    def evaluate_rules(self, audit: FundamentalAudit) -> FundamentalAudit:
        """Apply the 5 Golden Solvency & Quality rules."""
        failures: List[str] = []

        # Rule 1: Promoter Pledge == 0%
        if audit.promoter_pledge_pct is not None and audit.promoter_pledge_pct > 0.01:
            failures.append(f"Promoter pledge is {audit.promoter_pledge_pct}% (Must be 0%)")

        # Rule 2: Debt to Equity < 0.60
        if audit.debt_to_equity is not None and audit.debt_to_equity >= 0.60:
            failures.append(f"Debt/Equity is {audit.debt_to_equity:.2f} (Must be < 0.60)")

        # Rule 3: Interest Coverage > 3.5
        if audit.interest_coverage is not None and audit.interest_coverage <= 3.5:
            failures.append(f"Interest Coverage is {audit.interest_coverage:.2f} (Must be > 3.5)")

        # Rule 4: CFO > 0
        if audit.cfo_last_yr_cr is not None and audit.cfo_last_yr_cr <= 0:
            failures.append(f"Operating Cash Flow is ₹{audit.cfo_last_yr_cr} Cr (Must be > 0)")
        elif audit.cfo_last_yr_cr is None:
            failures.append("Operating Cash Flow data is missing")

        # Rule 5: ROCE >= 12%
        if audit.roce_pct is not None and audit.roce_pct < 12.0:
            failures.append(f"ROCE is {audit.roce_pct}% (Must be >= 12%)")
        elif audit.roce_pct is None:
            failures.append("ROCE metric is missing")

        audit.passed_audit = len(failures) == 0
        audit.failure_reasons = failures
        return audit

    def audit_company(self, symbol: str, force_refresh: bool = False) -> FundamentalAudit:
        """Audit a company with local cache support."""
        cache_path = self._get_cache_path(symbol)

        if not force_refresh and cache_path.exists():
            try:
                mtime = os.path.getmtime(cache_path)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return FundamentalAudit(**data)
            except Exception as e:
                logger.warning(f"Failed to read cache for {symbol}: {e}")

        # Fetch and parse
        try:
            html = self.fetch_html(symbol)
            audit = self.parse_html(symbol, html)
            # Write cache
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(audit.model_dump(), f, indent=2)
            return audit
        except Exception as e:
            # If network error but stale cache exists, return stale cache as fallback
            if cache_path.exists():
                logger.warning(f"Fetch failed for {symbol}, falling back to stale cache: {e}")
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return FundamentalAudit(**data)
            raise e

