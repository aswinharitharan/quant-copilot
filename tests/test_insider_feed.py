"""Unit tests for InsiderFeed SEBI PIT disclosures."""

import json
from pathlib import Path
import pytest
from src.scanner.insider_feed import InsiderFeed
from src.scanner.models import InsiderTradeRecord


RAW_NSE_SAMPLE = [
    {
        "symbol": "GOODCO",
        "acqName": "Promoter Alpha",
        "personCategory": "Promoters",
        "acqMode": "Market Purchase",
        "secAcq": "100000",
        "secVal": "25000000",  # ₹2.5 Cr
        "afterAcqSharesPer": "0.12",
        "date": "10-Nov-2026 14:00",
    },
    {
        "symbol": "GOODCO",
        "acqName": "Promoter Beta",
        "personCategory": "Promoters",
        "acqMode": "Market Purchase",
        "secAcq": "5000",
        "secVal": "500000",  # ₹5 Lakhs (immaterial)
        "afterAcqSharesPer": "0.00",
        "date": "08-Nov-2026 11:00",
    },
    {
        "symbol": "DUMPCO",
        "acqName": "Promoter Gamma",
        "personCategory": "Promoters",
        "acqMode": "Market Sale",
        "secAcq": "500000",
        "secVal": "80000000",  # Sale (not a buy)
        "afterAcqSharesPer": "2.5",
        "date": "09-Nov-2026 15:30",
    },
    {
        "symbol": "GIFTCO",
        "acqName": "Promoter Family Trust",
        "personCategory": "Promoter Group",
        "acqMode": "Gift",  # Gift / Inter-se (no fresh money)
        "secAcq": "2000000",
        "secVal": "500000000",
        "afterAcqSharesPer": "5.0",
        "date": "05-Nov-2026 10:15",
    },
    {
        "symbol": "DIRECTORCO",
        "acqName": "Managing Director X",
        "personCategory": "Director",
        "acqMode": "Open Market",
        "secAcq": "80000",
        "secVal": "12000000",  # ₹1.2 Cr
        "afterAcqSharesPer": "0.08",
        "date": "07-Nov-2026 16:00",
    },
]


def test_parse_nse_pit_records():
    feed = InsiderFeed()
    records = feed._parse_nse_items(RAW_NSE_SAMPLE)

    assert len(records) == 5

    # Record 0: Material promoter buy (> 1 Cr, Market Purchase)
    r0 = records[0]
    assert r0.symbol == "GOODCO"
    assert r0.value_inr == 25000000.0
    assert r0.is_material_promoter_buy is True

    # Record 1: Immaterial buy (< 1 Cr)
    r1 = records[1]
    assert r1.symbol == "GOODCO"
    assert r1.value_inr == 500000.0
    assert r1.is_material_promoter_buy is False

    # Record 2: Market Sale -> must be False
    r2 = records[2]
    assert r2.symbol == "DUMPCO"
    assert r2.is_material_promoter_buy is False

    # Record 3: Gift -> must be False
    r3 = records[3]
    assert r3.symbol == "GIFTCO"
    assert r3.is_material_promoter_buy is False

    # Record 4: Director Open Market buy (> 1 Cr) -> True
    r4 = records[4]
    assert r4.symbol == "DIRECTORCO"
    assert r4.is_material_promoter_buy is True


def test_get_symbol_insider_activity():
    feed = InsiderFeed()
    records = feed._parse_nse_items(RAW_NSE_SAMPLE)

    # GOODCO has two buys, should return the material ₹2.5 Cr one
    best_good = feed.get_symbol_insider_activity("GOODCO", records=records)
    assert best_good is not None
    assert best_good.value_inr == 25000000.0
    assert best_good.acquirer_name == "Promoter Alpha"

    # DUMPCO has no buys, only sales -> should return None
    dump_act = feed.get_symbol_insider_activity("DUMPCO", records=records)
    assert dump_act is None

    # GIFTCO has no open-market purchases -> should return None
    gift_act = feed.get_symbol_insider_activity("GIFTCO", records=records)
    assert gift_act is None


def test_insider_caching(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    feed = InsiderFeed(cache_dir=str(cache_dir), cache_ttl_hours=1)

    cached_records = [
        InsiderTradeRecord(
            symbol="CACHEDCO",
            filing_date="2026-11-10",
            acquirer_name="Mr. Promoter",
            category="Promoters",
            acquisition_mode="Market Purchase",
            quantity=50000,
            value_inr=15000000.0,
            is_material_promoter_buy=True,
        )
    ]

    cache_file = cache_dir / "nse_pit_disclosures.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump([r.model_dump() for r in cached_records], f)

    # Calling fetch_nse_pit should read from cache without network call
    loaded = feed.fetch_nse_pit()
    assert len(loaded) == 1
    assert loaded[0].symbol == "CACHEDCO"
    assert loaded[0].is_material_promoter_buy is True

