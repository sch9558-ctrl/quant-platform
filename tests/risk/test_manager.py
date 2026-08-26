import numpy as np
import pandas as pd
import pytest

from quant.risk.manager import PortfolioState, RiskManager

_CFG = {
    "position_limits": {
        "max_position_weight": 0.10, "max_sector_weight": 0.30, "max_strategy_weight": 0.40,
        "max_market_weight": 0.70, "min_cash_weight": 0.05, "max_gross_exposure": 1.0,
    },
    "loss_limits": {"max_daily_loss_pct": 0.03, "max_drawdown_pct": 0.20, "consecutive_loss_limit": 5},
    "position_sizing": {"method": "volatility_target", "target_annual_vol": 0.15, "vol_lookback_days": 20, "max_leverage": 1.0},
    "stops": {"use_stop_loss": True, "stop_loss_pct": 0.08, "use_trailing_stop": True, "trailing_stop_pct": 0.10},
    "correlation": {"max_pairwise_correlation": 0.85, "correlation_lookback_days": 60, "max_correlated_cluster_weight": 0.25},
}


def _state(**overrides) -> PortfolioState:
    base = dict(nav=1_000_000, peak_nav=1_000_000, positions={}, daily_pnl_pct=0.0, consecutive_losses=0)
    base.update(overrides)
    return PortfolioState(**base)


def test_position_size_capped():
    rm = RiskManager(_CFG)
    result = rm.check_order("AAA", 0.5, _state())
    assert result.approved_weight == pytest.approx(0.10)
    assert "position size capped" in result.reasons[0]


def test_daily_loss_limit_blocks_new_entries():
    rm = RiskManager(_CFG)
    result = rm.check_order("AAA", 0.05, _state(daily_pnl_pct=-0.05))
    assert result.approved_weight == 0.0
    assert not result.approved


def test_drawdown_limit_blocks_new_entries():
    rm = RiskManager(_CFG)
    result = rm.check_order("AAA", 0.05, _state(nav=750_000, peak_nav=1_000_000))
    assert result.approved_weight == 0.0


def test_consecutive_loss_limit_blocks_new_entries():
    rm = RiskManager(_CFG)
    result = rm.check_order("AAA", 0.05, _state(consecutive_losses=6))
    assert result.approved_weight == 0.0


def test_existing_position_can_still_be_held_during_drawdown_halt():
    rm = RiskManager(_CFG)
    # already holding 0.05 in AAA; a drawdown halt should not force it to
    # zero if the requested weight is <= what's already held (no NEW risk)
    result = rm.check_order("AAA", 0.05, _state(nav=750_000, peak_nav=1_000_000, positions={"AAA": 0.05}))
    assert result.approved_weight == pytest.approx(0.05)


def test_gross_exposure_cap():
    rm = RiskManager(_CFG)
    result = rm.check_order("NEW", 0.10, _state(positions={"X": 0.95}))
    assert result.approved_weight == pytest.approx(0.05, abs=1e-9)
    assert result.approved


def test_correlation_limit_blocks_highly_correlated_new_position():
    idx = pd.bdate_range("2023-01-01", periods=100)
    base = pd.Series(np.random.default_rng(0).normal(0, 0.01, 100), index=idx)
    highly_correlated = base * 1.02 + 0.0001  # near-perfect correlation

    rm = RiskManager(_CFG)
    state = _state(positions={"HELD": 0.05}, returns_history={"HELD": base, "NEW": highly_correlated})
    result = rm.check_order("NEW", 0.05, state)
    assert result.approved_weight == 0.0
    assert any("correlated" in r for r in result.reasons)


def test_position_size_volatility_target():
    rm = RiskManager(_CFG)
    size = rm.position_size(signal_strength=1.0, volatility=0.30)
    assert size == pytest.approx(0.15 / 0.30)


def test_position_size_respects_max_leverage():
    rm = RiskManager(_CFG)
    size = rm.position_size(signal_strength=1.0, volatility=0.05)  # would imply size 3.0
    assert size == pytest.approx(1.0)


def test_stop_loss_triggers():
    rm = RiskManager(_CFG)
    triggered, reason = rm.check_stop_loss(entry_price=100, current_price=90)
    assert triggered
    assert reason == "stop_loss"


def test_trailing_stop_triggers():
    rm = RiskManager(_CFG)
    triggered, reason = rm.check_stop_loss(entry_price=100, current_price=108, highest_price_since_entry=125)
    assert triggered
    assert reason == "trailing_stop"


def test_no_stop_when_price_healthy():
    rm = RiskManager(_CFG)
    triggered, reason = rm.check_stop_loss(entry_price=100, current_price=105, highest_price_since_entry=110)
    assert not triggered
    assert reason is None
