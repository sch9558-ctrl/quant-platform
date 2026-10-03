"""Deterministic model trade-plan generation for dashboard candidates.

This is a decision-support layer, not an execution engine. Every level is
derived from the same candidate snapshot that passed the data-quality gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class TradePlan:
    action: str
    action_ko: str
    current_price: float
    entry_low: float
    entry_high: float
    target_1: float
    target_2: float
    target_1_upside_pct: float
    target_2_upside_pct: float
    stop_loss: float
    stop_loss_pct: float
    risk_reward_1: float
    risk_reward_2: float
    holding_period_ko: str
    exit_rule_ko: str
    review_rule_ko: str
    model_confidence: int
    reasons_ko: list[str]
    note_ko: str = "모델 기반 매매 가이드이며 수익을 보장하지 않습니다."

    def to_dict(self):
        return asdict(self)


def _finite(value, default: float) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _risk_reward(entry: float, target: float, stop: float) -> float:
    risk = max(entry - stop, 0.0)
    reward = max(target - entry, 0.0)
    return round(reward / risk, 2) if risk > 0 else 0.0


def build_trade_plan(candidate) -> dict:
    price = max(_finite(getattr(candidate, "price", 0), 0), 1e-9)
    score = min(max(_finite(getattr(candidate, "composite_score", .5), .5), 0), 1)
    trend = _finite(getattr(candidate, "trend_score", 0), 0)
    momentum = min(max(_finite(getattr(candidate, "momentum_rank", .5), .5), 0), 1)
    risk = min(max(_finite(getattr(candidate, "risk_score", .5), .5), 0), 1)
    annual_vol = min(max(_finite(getattr(candidate, "volatility", .25), .25), .05), 1.5)
    edge = getattr(candidate, "historical_signal_edge", {}) or {}
    edge_n = int(edge.get("n_obs", 0) or 0)
    win_rate = _finite(edge.get("win_rate"), .5) if edge_n >= 5 else .5

    if score >= .74 and trend >= .10 and momentum >= .65 and risk <= .70:
        action, action_ko = "STRONG_BUY", "강력 매수(진입)"
    elif score >= .61 and trend >= -.05:
        action, action_ko = "BUY", "분할 매수"
    elif score >= .49:
        action, action_ko = "HOLD", "홀딩"
    elif score >= .39:
        action, action_ko = "TRIM", "분할 매도"
    else:
        action, action_ko = "AVOID", "손절/관망"

    # Volatility/risk-aware stop. These are deterministic research levels,
    # not ATR orders: candidate objects intentionally carry only the
    # validated cross-sectional snapshot.
    stop_pct = min(max(.04 + .035 * risk + .02 * min(annual_vol, .8), .04), .10)
    entry_discount = min(max(stop_pct * .45, .015), .045)
    entry_high = price * 1.005 if action == "STRONG_BUY" else price * (1 - entry_discount * .20)
    entry_low = price * (1 - entry_discount)

    t1_pct = min(max(stop_pct * 1.5 + max(trend, 0) * .02, .06), .18)
    t2_pct = min(max(stop_pct * 2.4 + max(momentum - .5, 0) * .10, .12), .32)
    target_1 = price * (1 + t1_pct)
    target_2 = price * (1 + t2_pct)
    stop_loss = price * (1 - stop_pct)

    if trend > .25 and momentum > .70:
        holding = "스윙~중기 (1~4개월)"
    elif momentum > .55:
        holding = "스윙 (3주~2개월)"
    else:
        holding = "단기 관찰 (1~4주)"

    entry_mid = (entry_low + entry_high) / 2
    rr1 = _risk_reward(entry_mid, target_1, stop_loss)
    rr2 = _risk_reward(entry_mid, target_2, stop_loss)

    if action in {"STRONG_BUY", "BUY", "HOLD"}:
        exit_rule = (
            "1차 목표 도달 시 일부 이익실현, 2차 목표 도달 시 잔여 물량을 재평가합니다. "
            "종가가 손절 기준선 아래로 내려가면 모델 시나리오를 종료합니다."
        )
    elif action == "TRIM":
        exit_rule = (
            "반등 시 분할 축소를 우선하며 신규 추격매수는 피합니다. "
            "손절 기준선 이탈 시 남은 포지션도 재평가합니다."
        )
    else:
        exit_rule = (
            "신규 진입을 보류합니다. 보유 중이라면 손절 기준선과 추세 회복 여부를 우선 확인합니다."
        )

    review_rule = (
        f"{holding} 범위 내에서도 1차 목표·손절선 도달, 데이터 품질 실패, "
        "시장 국면 전환 중 하나가 발생하면 즉시 다시 계산합니다."
    )

    confidence = round(
        100 * min(
            max(
                .45 * score
                + .20 * ((trend + 1) / 2)
                + .15 * momentum
                + .10 * (1 - risk)
                + .10 * win_rate,
                0,
            ),
            1,
        )
    )
    reasons = [
        f"종합 후보점수 {score:.2f}",
        f"모멘텀 백분위 {momentum:.2f}",
        f"추세점수 {trend:+.2f}",
        f"리스크점수 {risk:.2f}",
        f"1차 목표 손익비 {rr1:.2f}:1 · 2차 {rr2:.2f}:1",
    ]
    if edge_n >= 5:
        reasons.append(f"유사 과거신호 승률 {win_rate:.0%} (표본 {edge_n})")

    return TradePlan(
        action=action,
        action_ko=action_ko,
        current_price=round(price, 4),
        entry_low=round(entry_low, 4),
        entry_high=round(entry_high, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        target_1_upside_pct=round(t1_pct * 100, 2),
        target_2_upside_pct=round(t2_pct * 100, 2),
        stop_loss=round(stop_loss, 4),
        stop_loss_pct=round(-stop_pct * 100, 2),
        risk_reward_1=rr1,
        risk_reward_2=rr2,
        holding_period_ko=holding,
        exit_rule_ko=exit_rule,
        review_rule_ko=review_rule,
        model_confidence=confidence,
        reasons_ko=reasons,
    ).to_dict()
