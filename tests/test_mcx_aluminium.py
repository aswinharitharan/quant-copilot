"""
Unit tests for MCX Aluminium 200 SMA Enhanced Strategy.
"""

import pytest
from src.strategies.mcx_aluminium_200_sma_enhanced import get_mcx_aluminium_200_sma_enhanced_strategy


def test_mcx_aluminium_big_lot_strategy_schema():
    strat = get_mcx_aluminium_200_sma_enhanced_strategy(is_mini=False)
    assert strat.id == "mcx_aluminium_200_sma_enhanced"
    assert strat.underlying == "ALUMINIUM"
    assert len(strat.sets) == 2
    assert strat.sets[0].legs[0].leg_stop_loss_pct == 0.008
    assert strat.sets[0].legs[0].leg_target_pct == 0.015
    assert strat.deployment_settings.capital_allocated == 300000.0
    assert strat.deployment_settings.cooldown_bars_after_loss == 8
    assert strat.deployment_settings.intraday_square_off_time == "23:15:00"


def test_mcx_aluminium_mini_lot_strategy_schema():
    strat = get_mcx_aluminium_200_sma_enhanced_strategy(is_mini=True)
    assert strat.id == "mcx_alumini_200_sma_enhanced"
    assert strat.underlying == "ALUMINI"
    assert len(strat.sets) == 2
    assert strat.sets[0].legs[0].leg_stop_loss_pct == 0.008
    assert strat.sets[0].legs[0].leg_target_pct == 0.015
    assert strat.deployment_settings.capital_allocated == 75000.0
    assert strat.deployment_settings.intraday_square_off_time == "23:15:00"
