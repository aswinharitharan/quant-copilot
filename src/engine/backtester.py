"""
Deterministic Backtest Engine.

Simulates strategy execution bar-by-bar over historical OHLCV data with
full anti-lookahead guarantees, position lifecycle management,
risk sentinels (Max Daily Loss, Market Open Gate, Square-Off),
and realistic Indian market transaction costs.
"""

from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
import uuid
import pandas as pd

from src.schema.strategy import (
    StrategyDefinition,
    ExecutionStyle,
    InstrumentType,
    OrderAction,
    Leg,
)
from src.schema.backtest_models import Trade, BacktestResult
from src.engine.condition_evaluator import ConditionEvaluator
from src.engine.costs import TransactionCostModel, TradeCost
from src.engine.metrics import MetricsCalculator
from src.engine.expiry_calendar import ExpiryCalendar


class Backtester:
    """
    Deterministic Bar-by-Bar Backtest Engine.
    """

    def __init__(
        self,
        strategy: StrategyDefinition,
        cost_model: Optional[TransactionCostModel] = None,
        lot_size: int = 1,
        risk_free_rate: float = 0.065,
    ):
        self.strategy = strategy
        self.cost_model = cost_model or TransactionCostModel()
        self.lot_size = lot_size
        self.metrics_calculator = MetricsCalculator(risk_free_rate=risk_free_rate)

    def run(
        self,
        df: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """
        Execute deterministic backtest over the provided DataFrame.
        """
        if df.empty:
            raise ValueError("Input DataFrame is empty")

        df_work = df.copy()

        # Date range filtering if specified
        if start_date:
            df_work = df_work[df_work.index >= pd.to_datetime(start_date)]
        if end_date:
            df_work = df_work[df_work.index <= pd.to_datetime(end_date)]

        if df_work.empty:
            raise ValueError("DataFrame is empty after applying start/end date filters")

        # Ensure DTE column is present if underlying has monthly expiries
        if "days_to_expiry" not in df_work.columns:
            cal = ExpiryCalendar()
            df_work = cal.add_dte_column(df_work)

        # Pre-compute condition signals across all bars
        entry_signals: Dict[int, pd.Series] = {}
        exit_signals: Dict[int, pd.Series] = {}

        for s in self.strategy.sets:
            entry_signals[s.set_id] = ConditionEvaluator.evaluate_group(s.entry_conditions, df_work)
            if s.exit_conditions:
                exit_signals[s.set_id] = ConditionEvaluator.evaluate_group(s.exit_conditions, df_work)
            else:
                exit_signals[s.set_id] = pd.Series(False, index=df_work.index)

        universal_exit_series: Optional[pd.Series] = None
        if self.strategy.universal_exit:
            universal_exit_series = ConditionEvaluator.evaluate_group(self.strategy.universal_exit, df_work)

        # Simulation state
        deploy = self.strategy.deployment_settings
        initial_capital = deploy.capital_allocated
        current_cash = initial_capital

        open_positions: Dict[str, Trade] = {}  # key: f"{set_id}:{leg_id}"
        closed_trades: List[Trade] = []
        equity_records: Dict[datetime, float] = {}
        total_costs_paid = 0.0

        current_trading_day: Optional[datetime.date] = None
        daily_trades_count = 0
        is_locked_for_day = False
        today_realized_pnl = 0.0

        market_open_time = time(9, 15, 0)
        # Market open delay
        delay_minutes = deploy.market_open_delay_minutes
        allowed_start_time = (datetime.combine(datetime.today(), market_open_time) + timedelta(minutes=delay_minutes)).time()

        square_off_time: Optional[time] = None
        if deploy.execution_style == ExecutionStyle.INTRADAY and deploy.intraday_square_off_time:
            parts = [int(p) for p in deploy.intraday_square_off_time.split(":")]
            square_off_time = time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)

        is_intraday_mode = (deploy.execution_style == ExecutionStyle.INTRADAY)

        # Helper: close a specific open position
        def close_position(pos_key: str, bar_time: datetime, exit_price: float, reason: str):
            nonlocal current_cash, total_costs_paid, today_realized_pnl
            pos = open_positions.pop(pos_key)
            pos.exit_time = bar_time
            pos.exit_price = exit_price
            pos.exit_reason = reason

            # Calculate gross PnL
            if pos.action == OrderAction.BUY:
                pos.pnl_gross = (exit_price - pos.entry_price) * pos.quantity
            else:
                pos.pnl_gross = (pos.entry_price - exit_price) * pos.quantity

            # Exit transaction cost
            exit_action = OrderAction.SELL if pos.action == OrderAction.BUY else OrderAction.BUY
            exit_cost = self.cost_model.calculate(
                action=exit_action,
                instrument_type=pos.instrument_type,
                price=exit_price,
                quantity=pos.quantity,
                is_intraday=is_intraday_mode,
            )
            # Combine entry + exit costs
            entry_cost_total = pos.costs.total if pos.costs else 0.0
            total_trade_costs = entry_cost_total + exit_cost.total

            pos.costs.total = total_trade_costs
            pos.pnl_net = pos.pnl_gross - total_trade_costs

            current_cash += pos.pnl_net
            total_costs_paid += exit_cost.total
            today_realized_pnl += pos.pnl_net
            closed_trades.append(pos)

        # -------------------------------------------------------------
        # MAIN BAR-BY-BAR LOOP
        # -------------------------------------------------------------
        for current_time, bar in df_work.iterrows():
            bar_date = current_time.date()
            bar_time_of_day = current_time.time()
            close_price = float(bar["close"])

            # 1. Day transition reset
            if current_trading_day != bar_date:
                current_trading_day = bar_date
                daily_trades_count = 0
                is_locked_for_day = False
                today_realized_pnl = 0.0

            # 2. Universal Exit
            if universal_exit_series is not None and universal_exit_series.loc[current_time] and open_positions:
                for k in list(open_positions.keys()):
                    close_position(k, current_time, close_price, reason="UNIVERSAL_EXIT")

            # 3. Intraday Square-off
            if square_off_time and bar_time_of_day >= square_off_time and open_positions:
                for k in list(open_positions.keys()):
                    close_position(k, current_time, close_price, reason="INTRADAY_SQUARE_OFF")

            # 4. Check Individual Leg SL / Target and Set Exit Conditions
            if open_positions:
                for k, pos in list(open_positions.items()):
                    set_id = pos.set_id
                    # Leg Stop Loss / Target checks
                    entry_p = pos.entry_price
                    matched_leg: Optional[Leg] = None
                    for s in self.strategy.sets:
                        if s.set_id == set_id:
                            for l in s.legs:
                                if l.leg_id == pos.leg_id:
                                    matched_leg = l
                                    break

                    if matched_leg:
                        # Price change percentage
                        if pos.action == OrderAction.BUY:
                            ret = (close_price - entry_p) / entry_p
                        else:
                            ret = (entry_p - close_price) / entry_p

                        # Stop Loss
                        if matched_leg.leg_stop_loss_pct and ret <= -matched_leg.leg_stop_loss_pct:
                            close_position(k, current_time, close_price, reason="STOP_LOSS")
                            continue

                        # Target
                        if matched_leg.leg_target_pct and ret >= matched_leg.leg_target_pct:
                            close_position(k, current_time, close_price, reason="TARGET")
                            continue

                    # Set exit condition check
                    if exit_signals.get(set_id) is not None and exit_signals[set_id].loc[current_time]:
                        close_position(k, current_time, close_price, reason="SET_EXIT_CONDITION")

            # 5. Check Entry Conditions
            if not is_locked_for_day and bar_time_of_day >= allowed_start_time:
                for s in self.strategy.sets:
                    if daily_trades_count >= deploy.max_trades_per_day:
                        break

                    # Check if this set already has open positions
                    has_active = any(pos.set_id == s.set_id for pos in open_positions.values())
                    if not has_active and entry_signals[s.set_id].loc[current_time]:
                        # Enter all legs in set
                        for leg in s.legs:
                            qty = leg.lots * self.lot_size
                            pos_key = f"{s.set_id}:{leg.leg_id}"

                            entry_cost = self.cost_model.calculate(
                                action=leg.action,
                                instrument_type=leg.instrument_type,
                                price=close_price,
                                quantity=qty,
                                is_intraday=is_intraday_mode,
                            )
                            total_costs_paid += entry_cost.total

                            trade = Trade(
                                trade_id=str(uuid.uuid4())[:8],
                                set_id=s.set_id,
                                leg_id=leg.leg_id,
                                instrument_type=leg.instrument_type,
                                action=leg.action,
                                entry_time=current_time,
                                entry_price=close_price,
                                quantity=qty,
                                costs=entry_cost,
                            )
                            open_positions[pos_key] = trade

                        daily_trades_count += 1

            # 6. Mark to Market Equity
            unrealized_pnl = 0.0
            for pos in open_positions.values():
                if pos.action == OrderAction.BUY:
                    unrealized_pnl += (close_price - pos.entry_price) * pos.quantity
                else:
                    unrealized_pnl += (pos.entry_price - close_price) * pos.quantity

            current_equity = current_cash + unrealized_pnl
            equity_records[current_time] = round(current_equity, 2)

            # 7. Max Daily Loss Guard
            today_total_pnl = today_realized_pnl + unrealized_pnl
            if today_total_pnl <= -deploy.max_daily_loss and not is_locked_for_day:
                # Liquidate all open positions
                for k in list(open_positions.keys()):
                    close_position(k, current_time, close_price, reason="MAX_DAILY_LOSS")
                is_locked_for_day = True

        # End of backtest: close any remaining positions
        if open_positions:
            last_time = df_work.index[-1]
            last_price = float(df_work["close"].iloc[-1])
            for k in list(open_positions.keys()):
                close_position(k, last_time, last_price, reason="END_OF_BACKTEST")
            equity_records[last_time] = round(current_cash, 2)

        equity_curve = pd.Series(equity_records)
        metrics = self.metrics_calculator.calculate(
            equity_curve=equity_curve,
            trades=closed_trades,
            initial_capital=initial_capital,
        )

        return BacktestResult(
            strategy_id=self.strategy.id,
            strategy_name=self.strategy.name,
            underlying=self.strategy.underlying,
            timeframe=self.strategy.timeframe.value,
            start_date=str(df_work.index[0]),
            end_date=str(df_work.index[-1]),
            initial_capital=initial_capital,
            trades=closed_trades,
            equity_curve=equity_curve,
            metrics=metrics,
            total_costs=round(total_costs_paid, 2),
            config_snapshot=self.strategy.model_dump(),
        )
