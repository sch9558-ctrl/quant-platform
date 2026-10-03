from types import SimpleNamespace

from quant.analytics.trade_plan import build_trade_plan


def candidate(**overrides):
    base = dict(
        price=100.0,
        composite_score=.76,
        trend_score=.20,
        momentum_rank=.80,
        risk_score=.35,
        volatility=.24,
        historical_signal_edge={"n_obs": 20, "win_rate": .65},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_trade_plan_has_actionable_levels_and_positive_risk_reward():
    plan = build_trade_plan(candidate())
    assert plan["action"] == "STRONG_BUY"
    assert plan["entry_low"] < plan["entry_high"]
    assert plan["stop_loss"] < plan["entry_low"]
    assert plan["target_1"] > plan["current_price"]
    assert plan["target_2"] > plan["target_1"]
    assert plan["risk_reward_1"] > 0
    assert plan["risk_reward_2"] > plan["risk_reward_1"]
    assert "손절" in plan["exit_rule_ko"]
    assert "다시 계산" in plan["review_rule_ko"]


def test_weak_candidate_is_not_presented_as_buy():
    plan = build_trade_plan(candidate(
        composite_score=.30,
        trend_score=-.5,
        momentum_rank=.2,
        risk_score=.9,
    ))
    assert plan["action"] == "AVOID"
    assert plan["action_ko"] == "손절/관망"


def test_trade_plan_handles_missing_optional_metrics():
    plan = build_trade_plan(SimpleNamespace(price=50, composite_score=.5))
    assert 0 <= plan["model_confidence"] <= 100
    assert plan["stop_loss"] < 50
    assert plan["current_price"] == 50
