"""
Realistic Indian Market Transaction Cost & Friction Model.

Models Securities Transaction Tax (STT), Exchange Turnover Charges,
Goods and Services Tax (GST), SEBI Turnover Charges, Stamp Duty, and Slippage
for NSE Equities, Stock & Index Futures, and Options.
"""

from dataclasses import dataclass
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
        brokerage_per_order: float = 0.0,  # Zero-brokerage model (e.g. Dhan delivery / flat model)
        equity_slippage_pct: float = 0.0005,   # 0.05%
        futures_slippage_pct: float = 0.0005,  # 0.05%
        options_slippage_pct: float = 0.001,   # 0.10%
    ):
        self.brokerage_per_order = brokerage_per_order
        self.equity_slippage_pct = equity_slippage_pct
        self.futures_slippage_pct = futures_slippage_pct
        self.options_slippage_pct = options_slippage_pct

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
            stt = (turnover * 0.0002) if is_sell else 0.0  # 0.02% on sell (Budget 2024)
        elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
            stt = (turnover * 0.001) if is_sell else 0.0   # 0.1% on sell premium (Budget 2024)
        else:
            stt = 0.0

        # 2. Exchange Turnover Charges (NSE)
        if instrument_type == InstrumentType.EQUITY:
            exchange_charges = turnover * 0.0000345  # 0.00345%
        elif instrument_type == InstrumentType.FUTURES:
            exchange_charges = turnover * 0.00002    # 0.002%
        elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
            exchange_charges = turnover * 0.0005     # 0.05% on premium
        else:
            exchange_charges = 0.0

        # 3. GST (18% on Brokerage + Exchange Charges)
        gst = 0.18 * (brokerage + exchange_charges)

        # 4. SEBI Turnover Charges (₹10 per crore = 0.0001%)
        sebi_charges = turnover * 0.000001

        # 5. Stamp Duty (Buy side only)
        if is_buy:
            if instrument_type == InstrumentType.EQUITY:
                stamp_duty = turnover * (0.00003 if is_intraday else 0.00015)
            elif instrument_type == InstrumentType.FUTURES:
                stamp_duty = turnover * 0.00002  # 0.002%
            elif instrument_type in (InstrumentType.CE, InstrumentType.PE):
                stamp_duty = turnover * 0.00003  # 0.003%
            else:
                stamp_duty = 0.0
        else:
            stamp_duty = 0.0

        # 6. Slippage
        if instrument_type == InstrumentType.EQUITY:
            slippage_rate = self.equity_slippage_pct
        elif instrument_type == InstrumentType.FUTURES:
            slippage_rate = self.futures_slippage_pct
        else:
            slippage_rate = self.options_slippage_pct

        slippage_amount = turnover * slippage_rate

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
