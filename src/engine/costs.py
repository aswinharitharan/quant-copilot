"""
Realistic Indian Market Transaction Cost & Friction Model.

Models Securities Transaction Tax (STT), Exchange Turnover Charges,
Goods and Services Tax (GST), SEBI Turnover Charges, Stamp Duty, and Slippage
for NSE Equities, Stock & Index Futures, and Options.

Updated Rules:
1. Futures Slippage: ₹20 for BUY and ₹20 for SELL (₹40 round trip per order/lot).
2. Futures STT: 0.05% charged on the Sell value.
3. Exchange Turnover Charges: 0.00183% on total turnover.
4. State Stamp Duty: 0.002% on Buy side.
5. GST: 18% on (Slippage + SEBI Charges + Exchange Turnover Charges + Brokerage).
6. SEBI Charges: ₹10 per crore (0.0001% of turnover).
"""

from dataclasses import dataclass
from typing import Optional
from src.schema.strategy import InstrumentType, OrderAction


@dataclass
class TradeCost:
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    sebi_charges: float
    stamp_duty: float
    slippage_amount: float
    total: float


class TransactionCostModel:
    """
    Computes realistic Indian exchange taxes, statutory fees, and slippage.
    """

    def __init__(
        self,
        brokerage_per_order: float = 0.0,  # Zero-brokerage model (e.g. flat discount broker)
        equity_slippage_pct: float = 0.0005,  # 0.05%
        futures_slippage_pct: Optional[float] = None,  # If None and futures_slippage_fixed is set, uses fixed
        futures_slippage_fixed: Optional[float] = 20.0,  # ₹20 for buy, ₹20 for sell (₹40 round trip)
        options_slippage_pct: float = 0.001,  # 0.10%
        futures_stt_pct: float = 0.0005,  # 0.05% on sell value
        futures_exchange_pct: float = 0.0000183,  # 0.00183% on turnover
    ):
        self.brokerage_per_order = brokerage_per_order
        self.equity_slippage_pct = equity_slippage_pct
        self.futures_slippage_pct = futures_slippage_pct
        self.futures_slippage_fixed = futures_slippage_fixed
        self.options_slippage_pct = options_slippage_pct
        self.futures_stt_pct = futures_stt_pct
        self.futures_exchange_pct = futures_exchange_pct

    def calculate(
        self,
        action: OrderAction,
        instrument_type: InstrumentType,
        price: float,
        quantity: int,
        is_intraday: bool = True,
    ) -> TradeCost:
        """
        Calculate total transaction cost for an order execution.
        
        Args:
            action: OrderAction.BUY or OrderAction.SELL
            instrument_type: InstrumentType.EQUITY, FUTURES, CE, or PE
            price: Executed price per share/contract
            quantity: Total number of units (lots * lot_size)
            is_intraday: True if intraday, False for positional/delivery
        """
        turnover = price * quantity
        is_buy = (action == OrderAction.BUY)
        is_sell = (action == OrderAction.SELL)

        brokerage = self.brokerage_per_order

        # 1. STT (Securities Transaction Tax)
        if instrument_type == InstrumentType.EQUITY:
            if is_intraday:
                stt = (turnover * 0.00025) if is_sell else 0.0  # 0.025% on sell
            else:
                stt = turnover * 0.001  # 0.1% on buy & sell
        elif instrument_type == InstrumentType.FUTURES:
            stt = (turnover * self.futures_stt_pct) if is_sell else 0.0  # 0.05% on sell
        elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
            stt = (turnover * 0.001) if is_sell else 0.0   # 0.1% on sell premium
        else:
            stt = 0.0

        # 2. Exchange Turnover Charges (NSE)
        if instrument_type == InstrumentType.EQUITY:
            exchange_charges = turnover * 0.0000345  # 0.00345%
        elif instrument_type == InstrumentType.FUTURES:
            exchange_charges = turnover * self.futures_exchange_pct  # 0.00183%
        elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
            exchange_charges = turnover * 0.0005     # 0.05% on premium
        else:
            exchange_charges = 0.0

        # 3. SEBI Turnover Charges (₹10 per crore = 0.0001%)
        sebi_charges = turnover * 0.000001

        # 4. Stamp Duty (Buy side only)
        if is_buy:
            if instrument_type == InstrumentType.EQUITY:
                stamp_duty = turnover * (0.00003 if is_intraday else 0.00015)
            elif instrument_type == InstrumentType.FUTURES:
                stamp_duty = turnover * 0.00002  # 0.002% on buy side
            elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
                stamp_duty = turnover * 0.00003  # 0.003%
            else:
                stamp_duty = 0.0
        else:
            stamp_duty = 0.0

        # 5. Slippage (₹20 buy, ₹20 sell for Futures or percentage if specified)
        if instrument_type == InstrumentType.FUTURES:
            if self.futures_slippage_pct is not None:
                slippage_amount = turnover * self.futures_slippage_pct
            elif self.futures_slippage_fixed is not None:
                slippage_amount = self.futures_slippage_fixed
            else:
                slippage_amount = turnover * 0.0005
        elif instrument_type == InstrumentType.EQUITY:
            slippage_amount = turnover * self.equity_slippage_pct
        else:
            slippage_amount = turnover * self.options_slippage_pct

        # 6. GST (18% on Slippage + SEBI Charges + Exchange Charges + Brokerage)
        gst = 0.18 * (brokerage + exchange_charges + sebi_charges + slippage_amount)

        total = (
            brokerage
            + stt
            + exchange_charges
            + gst
            + sebi_charges
            + stamp_duty
            + slippage_amount
        )

        return TradeCost(
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_charges=round(exchange_charges, 2),
            gst=round(gst, 2),
            sebi_charges=round(sebi_charges, 2),
            stamp_duty=round(stamp_duty, 2),
            slippage_amount=round(slippage_amount, 2),
            total=round(total, 2),
        )
