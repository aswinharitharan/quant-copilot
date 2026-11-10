"""Unit tests for ScreenerClient fundamental auditor."""

import json
from pathlib import Path
import pytest
from src.scanner.models import FundamentalAudit
from src.scanner.screener_client import ScreenerClient


SAMPLE_HEALTHY_HTML = """
<html>
<body>
  <div id="company-info" data-company-id="3412"></div>
  <ul id="top-ratios">
    <li><span class="name">Market Cap</span><span class="value">₹33,196Cr.</span></li>
    <li><span class="name">Current Price</span><span class="value">₹2,786</span></li>
    <li><span class="name">Stock P/E</span><span class="value">60.9</span></li>
    <li><span class="name">ROCE</span><span class="value">13.9%</span></li>
    <li><span class="name">ROE</span><span class="value">10.6%</span></li>
  </ul>
  <table id="balance-sheet">
    <tr><td>Equity Capital</td><td>23</td><td>23</td></tr>
    <tr><td>Reserves</td><td>4,500</td><td>5,462</td></tr>
    <tr><td>Borrowings</td><td>1,200</td><td>2,000</td></tr>
  </table>
  <table id="profit-loss">
    <tr><td>Operating Profit</td><td>600</td><td>892</td></tr>
    <tr><td>Interest</td><td>100</td><td>149</td></tr>
  </table>
  <table id="cash-flow">
    <tr><td>Cash from Operating Activity</td><td>400</td><td>542</td></tr>
  </table>
  <table id="shareholding">
    <tr><td>Promoters</td><td>61.99%</td></tr>
  </table>
</body>
</html>
"""

SAMPLE_DISTRESSED_HTML = """
<html>
<body>
  <ul id="top-ratios">
    <li><span class="name">Market Cap</span><span class="value">₹1,500Cr.</span></li>
    <li><span class="name">Current Price</span><span class="value">₹12.5</span></li>
    <li><span class="name">ROCE</span><span class="value">3.2%</span></li>
  </ul>
  <table id="balance-sheet">
    <tr><td>Equity Capital</td><td>100</td></tr>
    <tr><td>Reserves</td><td>-300</td></tr>
    <tr><td>Borrowings</td><td>2,500</td></tr>
  </table>
  <table id="profit-loss">
    <tr><td>Operating Profit</td><td>50</td></tr>
    <tr><td>Interest</td><td>120</td></tr>
  </table>
  <table id="cash-flow">
    <tr><td>Cash from Operating Activity</td><td>-85</td></tr>
  </table>
  <table id="shareholding">
    <tr><td>Promoters</td><td>35.0%</td></tr>
    <tr><td>Pledged %</td><td>45.0%</td></tr>
  </table>
</body>
</html>
"""


def test_parse_healthy_html():
    client = ScreenerClient()
    audit = client.parse_html("HEALTHYCO", SAMPLE_HEALTHY_HTML)

    assert audit.symbol == "HEALTHYCO"
    assert audit.market_cap_cr == 33196.0
    assert audit.current_price == 2786.0
    assert audit.pe_ratio == 60.9
    assert audit.roce_pct == 13.9
    # Net worth = 23 + 5462 = 5485. Borrowings = 2000. D/E = 2000/5485 = 0.36
    assert audit.debt_to_equity == 0.36
    # Op profit = 892, Interest = 149. Coverage = 892/149 = 5.99
    assert audit.interest_coverage == 5.99
    assert audit.cfo_last_yr_cr == 542.0
    assert audit.promoter_holding_pct == 61.99
    assert audit.promoter_pledge_pct == 0.0
    assert audit.passed_audit is True
    assert len(audit.failure_reasons) == 0


def test_parse_distressed_html():
    client = ScreenerClient()
    audit = client.parse_html("DISTRESSEDCO", SAMPLE_DISTRESSED_HTML)

    assert audit.symbol == "DISTRESSEDCO"
    assert audit.passed_audit is False
    # Should fail on: pledge, D/E (negative net worth), interest coverage, negative CFO, ROCE < 12%
    assert len(audit.failure_reasons) >= 4
    reasons_str = " ".join(audit.failure_reasons)
    assert "pledge" in reasons_str.lower()
    assert "roce" in reasons_str.lower()
    assert "operating cash flow" in reasons_str.lower()


def test_zero_debt_infinite_coverage():
    client = ScreenerClient()
    raw = FundamentalAudit(
        symbol="CASHCO",
        audit_date="2026-11-10",
        market_cap_cr=50000.0,
        current_price=1500.0,
        pe_ratio=30.0,
        roce_pct=25.0,
        debt_to_equity=0.0,
        interest_coverage=999.0, # zero debt
        cfo_last_yr_cr=3500.0,
        promoter_holding_pct=72.0,
        promoter_pledge_pct=0.0,
    )
    evaluated = client.evaluate_rules(raw)
    assert evaluated.passed_audit is True
    assert len(evaluated.failure_reasons) == 0


def test_screener_caching(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    client = ScreenerClient(cache_dir=str(cache_dir), cache_ttl_hours=1)

    # Pre-populate cache
    cached_audit = FundamentalAudit(
        symbol="TESTCO",
        audit_date="2026-11-10",
        market_cap_cr=1000.0,
        roce_pct=15.0,
        debt_to_equity=0.2,
        interest_coverage=8.0,
        cfo_last_yr_cr=120.0,
        promoter_holding_pct=60.0,
        promoter_pledge_pct=0.0,
        passed_audit=True,
    )
    cache_file = cache_dir / "fundamentals_TESTCO.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cached_audit.model_dump(), f)

    # Calling audit_company should load directly from cache without network
    loaded = client.audit_company("TESTCO")
    assert loaded.symbol == "TESTCO"
    assert loaded.market_cap_cr == 1000.0
    assert loaded.passed_audit is True

