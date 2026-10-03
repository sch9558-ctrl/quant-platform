from types import SimpleNamespace
from quant.analytics.trade_plan import build_trade_plan

def _c(score=.8,trend=.3,mom=.8,risk=.3,vol=.25):
    return SimpleNamespace(price=100.0,composite_score=score,trend_score=trend,momentum_rank=mom,risk_score=risk,volatility=vol,historical_signal_edge={"n_obs":20,"win_rate":.65})

def test_trade_plan_has_ordered_levels_and_korean_action():
    p=build_trade_plan(_c())
    assert p["action_ko"]=="강력 매수(진입)"
    assert p["stop_loss"] < p["entry_low"] < p["entry_high"] < p["target_1"] < p["target_2"]
    assert 0<=p["model_confidence"]<=100

def test_weak_candidate_is_not_marked_buy():
    p=build_trade_plan(_c(score=.25,trend=-.6,mom=.2,risk=.9))
    assert p["action"]=="AVOID"
