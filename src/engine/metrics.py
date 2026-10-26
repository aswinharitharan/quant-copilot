"""
Performance & Risk Metrics Suite for Backtesting.

Computes CAGR, Sharpe, Sortino, Calmar, Max Drawdown, Win Rate,
Profit Factor, and Expectancy against Indian benchmark rates.
"""

from typing import List, Dict, Any
import numpy as np
import pandas as pd
from src.schema.backtest_models import Trade


class MetricsCalculator:
    """
    Computes portfolio performance and risk metrics.
    """

    def __init__(self, risk_free_rate: float = 0.065):  # 6.5% default RBI repo rate
        self.risk_free_rate = risk_free_rate

    def calculate(
        self,
        equity_curve: pd.Series,
        trades: List[Trade],
        initial_capital: float,
    ) -> Dict[str, Any]:
        """
        Calculate full suite of performance metrics.
        """
        metrics: Dict[str, Any] = {}

        if equity_curve.empty or len(equity_curve) < 2:
            return self._empty_metrics(initial_capital)

        # 1. Equity & Returns
        final_equity = float(equity_curve.iloc[-1])
        total_pnl = final_equity - initial_capital
        total_return_pct = (total_pnl / initial_capital) * 100.0

        # Daily resampled returns for Sharpe/Volatility
        if isinstance(equity_curve.index, pd.DatetimeIndex):
            daily_equity = equity_curve.resample("1D").last().dropna()
        else:
            daily_equity = equity_curve

        trading_days = max(1, len(daily_equity))
        years = trading_days / 252.0

        if years > 0 and final_equity > 0:
            cagr = ((final_equity / initial_capital) ** (1.0 / years) - 1.0) * 100.0
        else:
            cagr = 0.0

        daily_returns = daily_equity.pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            annualized_vol = float(daily_returns.std() * np.sqrt(252.0))
            # Sharpe
            annualized_ret = (daily_returns.mean() * 252.0)
            sharpe = (annualized_ret - self.risk_free_rate) / annualized_vol
            # Sortino
            downside_returns = daily_returns[daily_returns < 0]
            downside_vol = float(downside_returns.std() * np.sqrt(252.0)) if len(downside_returns) > 0 else 0.0
            sortino = (annualized_ret - self.risk_free_rate) / downside_vol if downside_vol > 0 else 0.0
        else:
            annualized_vol = 0.0
            sharpe = 0.0
            sortino = 0.0

        # 2. Drawdowns
        running_max = equity_curve.cummax()
        drawdown_series = (equity_curve - running_max) / running_max
        max_drawdown_pct = float(abs(drawdown_series.min()) * 100.0)

        # Calmar Ratio
        calmar = (cagr / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

        # Drawdown Duration (in days)
        max_dd_duration_days = 0
        if isinstance(equity_curve.index, pd.DatetimeIndex):
            is_dd = equity_curve < running_max
            # Find longest consecutive period of drawdown
            cur_dd_start = None
            for ts, in_dd in is_dd.items():
                if in_dd:
                    if cur_dd_start is None:
                        cur_dd_start = ts
                    duration = (ts - cur_dd_start).days
                    if duration > max_dd_duration_days:
                        max_dd_duration_days = duration
                else:
                    cur_dd_start = None

        # 3. Trade Metrics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.pnl_net and t.pnl_net > 0]
        losing_trades = [t for t in trades if t.pnl_net and t.pnl_net <= 0]

        win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profit = sum(t.pnl_net for t in winning_trades) if winning_trades else 0.0
        gross_loss = abs(sum(t.pnl_net for t in losing_trades)) if losing_trades else 0.0

        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 2)
        else:
            profit_factor = round(gross_profit, 2) if gross_profit > 0 else 0.0

        expectancy = (total_pnl / total_trades) if total_trades > 0 else 0.0

        metrics.update(
            {
                "initial_capital": round(initial_capital, 2),
                "final_equity": round(final_equity, 2),
                "total_pnl": round(total_pnl, 2),
                "total_return_pct": round(total_return_pct, 2),
                "cagr_pct": round(cagr, 2),
                "annualized_volatility_pct": round(annualized_vol * 100.0, 2),
                "sharpe_ratio": round(sharpe, 2),
                "sortino_ratio": round(sortino, 2),
                "calmar_ratio": round(calmar, 2),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "max_drawdown_duration_days": int(max_dd_duration_days),
                "total_trades": total_trades,
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate_pct": round(win_rate, 2),
                "profit_factor": profit_factor,
                "expectancy_inr": round(expectancy, 2),
            }
        )

        return metrics

    def _empty_metrics(self, initial_capital: float) -> Dict[str, Any]:
        return {
            "initial_capital": round(initial_capital, 2),
            "final_equity": round(initial_capital, 2),
            "total_pnl": 0.0,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "annualized_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_duration_days": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy_inr": 0.0,
        }
