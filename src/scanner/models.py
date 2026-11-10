"""Pydantic data models for QuantCopilot's 52-Week Strategy & Scanner."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# 1. ENUMS
# -------------------------------------------------------------------------

class StockStatusBadge(str, Enum):
    """Daily status badge for active holdings based on distance to soft stop and targets."""
    SAFE = "SAFE"                  # > 3% above capitulation low
    RADAR_ALERT = "RADAR_ALERT"    # Within 1.5% of capitulation low (testing support)
    DECISION_REQD = "DECISION_REQD"# Closed below capitulation low on EOD basis
    TARGET_1_HIT = "TARGET_1_HIT"  # Crossed 20 EMA (suggest 50% book or trail)
    TARGET_2_HIT = "TARGET_2_HIT"  # Crossed 50 EMA (suggest full book or tight trail)


class SignalStage(str, Enum):
    """Lifecycle stage for capitulation signals."""
    RADAR = "RADAR"                # Day 1: 52W low hit on huge volume + passed audit
    CONFIRMED_BUY = "CONFIRMED_BUY"# Day 2+: Closed above confirmation pivot/5 EMA
    INVALIDATED = "INVALIDATED"    # Broke below capitulation low before confirmation


class SellReason(str, Enum):
    """Reason for booking partial or full sale."""
    TARGET_1 = "TARGET_1"          # 20 EMA mean reversion
    TARGET_2 = "TARGET_2"          # 50 EMA primary target
    STOP_LOSS = "STOP_LOSS"        # Invalidation below capitulation low
    MANUAL = "MANUAL"              # Discretionary user exit


# -------------------------------------------------------------------------
# 2. FUNDAMENTAL AUDIT & INSIDER MODELS
# -------------------------------------------------------------------------

class FundamentalAudit(BaseModel):
    """Result of Screener.in fundamental solvency & quality audit."""
    symbol: str
    audit_date: str
    market_cap_cr: Optional[float] = None
    current_price: Optional[float] = None
    pe_ratio: Optional[float] = None
    roce_pct: Optional[float] = None
    roe_pct: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None
    cfo_last_yr_cr: Optional[float] = None
    promoter_holding_pct: Optional[float] = None
    promoter_pledge_pct: Optional[float] = None
    passed_audit: bool = False
    failure_reasons: List[str] = Field(default_factory=list)


class InsiderTradeRecord(BaseModel):
    """Record of SEBI PIT (Prohibition of Insider Trading) disclosure."""
    symbol: str
    filing_date: str
    acquirer_name: str
    category: str                  # e.g., "Promoter", "Director", "KMP"
    acquisition_mode: str          # e.g., "Market Purchase", "Open Market"
    quantity: int
    value_inr: float
    percent_equity: Optional[float] = None
    is_material_promoter_buy: bool = False  # True if open market & >= ₹1 Cr or >= 0.05% equity


# -------------------------------------------------------------------------
# 3. SCANNER SIGNALS & WATCHLIST (TIER 1)
# -------------------------------------------------------------------------

class CapitulationSignal(BaseModel):
    """Technical 52-Week Low Capitulation Signal."""
    symbol: str
    capitulation_date: str
    low_price: float
    high_price: float
    close_price: float
    today_volume: int
    avg_volume_20d: float
    volume_ratio: float            # today_volume / avg_volume_20d
    support_sl: float              # Capitulation candle low
    target_1_20ema: float          # 20 EMA level
    target_2_50ema: float          # 50 EMA level
    audit: FundamentalAudit
    insider_activity: Optional[InsiderTradeRecord] = None
    stage: SignalStage = SignalStage.RADAR
    confirmation_date: Optional[str] = None
    confirmation_price: Optional[float] = None


class WatchlistStock(BaseModel):
    """Tier 1: Stocks the user selected to watch for Stage 2 Buy Trigger."""
    symbol: str
    added_date: str
    capitulation_date: str
    capitulation_low: float
    capitulation_high: float
    target_1_20ema: float
    target_2_50ema: float
    notes: Optional[str] = ""
    is_buy_triggered: bool = False
    trigger_date: Optional[str] = None
    trigger_price: Optional[float] = None


# -------------------------------------------------------------------------
# 4. ACTIVE PORTFOLIO & AUDIT LEDGER (TIER 2 & TIER 3)
# -------------------------------------------------------------------------

class TradeSellRecord(BaseModel):
    """Record of a partial or full sell execution."""
    sell_date: str
    quantity: int
    sell_price: float
    reason: SellReason
    proceeds_inr: float
    realized_pnl_inr: float
    realized_pnl_pct: float


class PortfolioStock(BaseModel):
    """Tier 2: Active holdings currently owned and monitored daily."""
    symbol: str
    entry_date: str
    entry_price: float
    total_quantity_bought: int
    remaining_quantity: int
    capitulation_low: float        # Soft Stop-Loss baseline
    target_1_20ema: float
    target_2_50ema: float
    current_price: float
    dist_from_sl_pct: float        # (current_price - capitulation_low) / capitulation_low * 100
    unrealized_pnl_pct: float      # (current_price - entry_price) / entry_price * 100
    status_badge: StockStatusBadge = StockStatusBadge.SAFE
    partial_sells: List[TradeSellRecord] = Field(default_factory=list)


class ClosedTradeLedger(BaseModel):
    """Tier 3: Permanent historical ledger of completely exited trades."""
    symbol: str
    entry_date: str
    entry_price: float
    total_quantity: int
    total_invested_inr: float
    sells: List[TradeSellRecord] = Field(default_factory=list)
    final_exit_date: str
    total_proceeds_inr: float
    net_realized_pnl_inr: float
    net_return_pct: float
    holding_duration_days: int


# -------------------------------------------------------------------------
# 5. DAILY DASHBOARD
# -------------------------------------------------------------------------

class DailyDashboard52(BaseModel):
    """Daily executive briefing payload for 'Whats today for 52'."""
    as_of_date: str
    new_radar_signals: List[CapitulationSignal] = Field(default_factory=list)
    watchlist_buy_triggers: List[WatchlistStock] = Field(default_factory=list)
    active_portfolio_status: List[PortfolioStock] = Field(default_factory=list)
    material_insider_trades: List[InsiderTradeRecord] = Field(default_factory=list)
    summary_notes: List[str] = Field(default_factory=list)

