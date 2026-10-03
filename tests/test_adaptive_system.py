from __future__ import annotations

import pandas as pd
import pytest

from quant.analytics.adaptive_optimizer import AdaptiveOptimizer
from quant.analytics.calibrator import TargetPriceCalibrator
from quant.analytics.performance_tracker import PerformanceTracker, PredictionSnapshot
from quant.analytics.risk_manager import TradeRiskManager


def _prices(n=120, start="2026-01-02"):
    idx=pd.bdate_range(start,periods=n)
    close=pd.Series([100+i*0.2 for i in range(n)],index=idx)
    return pd.DataFrame({"open":close-0.3,"high":close+1.0,"low":close-1.0,"close":close,"volume":1000},index=idx)


def test_target_price_calibrator_bias_and_signal():
    df=_prices()
    reports=[
        {"analyst":"A","published_at":"2026-01-05","target_price":130},
        {"analyst":"A","published_at":"2026-02-02","target_price":135},
    ]
    cal=TargetPriceCalibrator(lookback_years=2,horizon_months=3)
    bias=cal.calculate_analyst_bias("A",reports,df)
    assert bias > 0
    target=cal.calibrate_target_price(130,bias,0.95)
    assert 0 < target < 130
    signal=cal.generate_trade_signal(100,120,92)
    assert signal.decision=="BUY"
    assert signal.risk_reward_ratio==pytest.approx(2.5)


def test_trade_signal_stop_loss_precedes_sell():
    signal=TargetPriceCalibrator.generate_trade_signal(90,105,90)
    assert signal.decision=="STOP_LOSS"


def test_performance_tracker_target_first(tmp_path):
    tracker=PerformanceTracker(tmp_path/"predictions.jsonl")
    snap=PredictionSnapshot(
        prediction_id="x",market="us",symbol="AAA",generated_at="2026-01-02",
        entry_price=100,target_price=110,stop_price=95,expiry_date="2026-02-28",
    )
    idx=pd.bdate_range("2026-01-02",periods=10)
    df=pd.DataFrame({"high":[101,104,111,112,113,114,115,116,117,118],
                     "low":[99,98,97,96,97,98,99,100,101,102],
                     "close":[100,102,109,111,112,113,114,115,116,117]},index=idx)
    out=tracker.evaluate(snap,df)
    assert out.outcome=="TARGET_REACHED"
    assert out.realized_return==pytest.approx(0.10)
    assert out.realized_risk_reward==pytest.approx(2.0)
    assert out.mfe > 0 and out.mae < 0


def test_adaptive_optimizer_grid_search_smooths_alpha():
    rows=[]
    for i in range(20):
        rows.append({
            "generated_at":str(pd.Timestamp("2026-08-01",tz="UTC")+pd.Timedelta(days=i)),
            "entry_price":100.0,"target_price":120.0,"mfe":0.08,
            "outcome":"TARGET_REACHED" if i<12 else "EXPIRED","analyst_id":"A",
        })
    state=AdaptiveOptimizer(lookback_months=6,ema_smoothing=0.5).optimize_alpha(rows,previous_alpha=0.0)
    assert 0 < state.alpha < 0.2
    assert state.rmse is not None
    assert state.n_obs==20
    assert 0 <= state.analyst_weight <= 1


def test_atr_position_sizing_respects_risk_and_max_weight():
    df=_prices(40)
    mgr=TradeRiskManager(account_risk_pct=0.01,max_position_pct=0.10,atr_multiple=2.0)
    plan=mgr.build_plan(df,portfolio_value=10_000_000)
    assert plan.quantity > 0
    assert plan.stop_price < float(df["close"].iloc[-1])
    assert plan.portfolio_weight <= 0.10 + 1e-12
    assert plan.quantity*plan.risk_per_share <= 100_000 + plan.risk_per_share


def test_sector_and_position_constraints():
    assert TradeRiskManager.sector_capacity({"tech":0.20},"tech",0.10)
    assert not TradeRiskManager.sector_capacity({"tech":0.25},"tech",0.10)
    assert TradeRiskManager.position_count_allowed(11,12)
    assert not TradeRiskManager.position_count_allowed(12,12)
