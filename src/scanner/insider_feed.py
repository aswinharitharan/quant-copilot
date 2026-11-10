"""NSE SEBI PIT (Prohibition of Insider Trading) Disclosure Feed.

Fetches and filters insider trading disclosures to isolate high-conviction
Promoter / Director open-market purchases (Regulation 7(2)).
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests
from src.scanner.models import InsiderTradeRecord

logger = logging.getLogger(__name__)


class InsiderFeed:
    """Client to fetch, cache, and filter material promoter & insider transactions."""

    NSE_PIT_URL = "https://www.nseindia.com/api/corporates-pit?index=equities"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    PROMOTER_CATEGORIES = {
        "promoter",
        "promoters",
        "promoter group",
        "director",
        "key managerial personnel",
        "kmp",
        "immediate relative",
    }

    OPEN_MARKET_MODES = {
        "market purchase",
        "open market",
        "market purchases",
    }

    def __init__(self, cache_dir: str = "data/cache", cache_ttl_hours: int = 12):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self.cache_file = self.cache_dir / "nse_pit_disclosures.json"

    def _clean_float(self, val: Optional[str]) -> float:
        if not val or val == "-":
            return 0.0
        try:
            return float(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0.0

    def fetch_nse_pit(
        self, from_date: Optional[str] = None, to_date: Optional[str] = None, force_refresh: bool = False
    ) -> List[InsiderTradeRecord]:
        """Fetch SEBI PIT disclosures from NSE with caching.

        Dates expected in DD-MM-YYYY format. Defaults to last 45 days.
        """
        now = datetime.now()
        if not to_date:
            to_date = now.strftime("%d-%m-%Y")
        if not from_date:
            from_date = (now - timedelta(days=45)).strftime("%d-%m-%Y")

        # Check cache
        if not force_refresh and self.cache_file.exists():
            try:
                mtime = os.path.getmtime(self.cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(self.cache_file, "r", encoding="utf-8") as f:
                        raw_items = json.load(f)
                    return [InsiderTradeRecord(**item) for item in raw_items]
            except Exception as e:
                logger.warning(f"Failed to read insider cache: {e}")

        # Fetch from NSE
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": self.DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
            }
        )

        url = f"{self.NSE_PIT_URL}&from_date={from_date}&to_date={to_date}"
        try:
            resp = s.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_data = data.get("data", [])
                records = self._parse_nse_items(raw_data)

                # Save cache
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump([r.model_dump() for r in records], f, indent=2)

                return records
            else:
                logger.warning(f"NSE PIT API returned status {resp.status_code}")
        except Exception as e:
            logger.warning(f"NSE PIT API fetch error: {e}")

        # Fallback to stale cache if present
        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw_items = json.load(f)
            return [InsiderTradeRecord(**item) for item in raw_items]

        return []

    def _parse_nse_items(self, items: List[Dict]) -> List[InsiderTradeRecord]:
        """Convert raw NSE dict items into InsiderTradeRecord objects."""
        parsed: List[InsiderTradeRecord] = []
        for it in items:
            sym = str(it.get("symbol") or "").upper().strip()
            if not sym or sym == "-":
                continue

            name = str(it.get("acqName") or "Unknown").strip()
            cat = str(it.get("personCategory") or "Other").strip()
            mode = str(it.get("acqMode") or "Other").strip()
            date_str = str(it.get("date") or it.get("intimDt") or "").strip()

            sec_acq = int(self._clean_float(it.get("secAcq") or it.get("buyQuantity")))
            sec_val = self._clean_float(it.get("secVal") or it.get("buyValue"))
            pct_equity = self._clean_float(it.get("afterAcqSharesPer"))

            # Determine if this is a material promoter open market buy
            is_promoter = any(p in cat.lower() for p in self.PROMOTER_CATEGORIES)
            is_market_buy = any(m in mode.lower() for m in self.OPEN_MARKET_MODES)
            is_material_val = sec_val >= 10_000_000.0  # ₹1 Crore
            is_material_pct = pct_equity >= 0.05       # 0.05% of company

            is_material = is_promoter and is_market_buy and (is_material_val or is_material_pct)

            parsed.append(
                InsiderTradeRecord(
                    symbol=sym,
                    filing_date=date_str,
                    acquirer_name=name,
                    category=cat,
                    acquisition_mode=mode,
                    quantity=sec_acq,
                    value_inr=sec_val,
                    percent_equity=pct_equity if pct_equity > 0 else None,
                    is_material_promoter_buy=is_material,
                )
            )
        return parsed

    def get_symbol_insider_activity(
        self, symbol: str, records: Optional[List[InsiderTradeRecord]] = None
    ) -> Optional[InsiderTradeRecord]:
        """Return the most material promoter buy for a given symbol, if any exists."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        if records is None:
            records = self.fetch_nse_pit()

        matches = [r for r in records if r.symbol == clean_sym and r.is_material_promoter_buy]
        if not matches:
            return None

        # Sort by value descending to return highest-conviction transaction
        matches.sort(key=lambda x: x.value_inr, reverse=True)
        return matches[0]

