"""Trading-cost and liquidity impact model."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ExecutionCost:
    participation_rate: float
    impact_bps: float
    half_spread_bps: float
    exchange_fee_bps: float
    total_one_way_bps: float


@dataclass(frozen=True)
class NetAlphaAssessment:
    gross_alpha_pct: float
    estimated_cost_pct: float
    net_alpha_pct: float
    accepted: bool
    reason: str
    cost: ExecutionCost


class ExecutionModel:
    """Square-root market-impact model with explicit units.

    sigma is a decimal volatility estimate (for example 0.02 = 2%).
    order_notional and adv_notional must use the same currency.
    """
    def __init__(self, gamma: float = 0.10, min_net_alpha_pct: float = 3.0):
        if gamma < 0:
            raise ValueError("gamma must be non-negative")
        self.gamma = float(gamma)
        self.min_net_alpha_pct = float(min_net_alpha_pct)

    def estimate_cost(
        self,
        *,
        order_notional: float,
        adv_notional: float,
        sigma: float,
        half_spread_bps: float,
        exchange_fee_bps: float = 0.0,
    ) -> ExecutionCost:
        if order_notional < 0 or adv_notional <= 0 or sigma < 0:
            raise ValueError("order_notional/sigma must be non-negative and ADV positive")
        participation = order_notional / adv_notional
        impact_decimal = self.gamma * float(sigma) * math.sqrt(max(participation, 0.0))
        impact_bps = impact_decimal * 10_000.0
        total = impact_bps + max(float(half_spread_bps), 0.0) + max(float(exchange_fee_bps), 0.0)
        return ExecutionCost(
            participation_rate=float(participation),
            impact_bps=float(impact_bps),
            half_spread_bps=float(max(half_spread_bps, 0.0)),
            exchange_fee_bps=float(max(exchange_fee_bps, 0.0)),
            total_one_way_bps=float(total),
        )

    def assess_signal(
        self,
        *,
        gross_alpha_pct: float,
        order_notional: float,
        adv_notional: float,
        sigma: float,
        half_spread_bps: float,
        exchange_fee_bps: float = 0.0,
        round_trip: bool = True,
        min_net_alpha_pct: float | None = None,
    ) -> NetAlphaAssessment:
        cost = self.estimate_cost(
            order_notional=order_notional,
            adv_notional=adv_notional,
            sigma=sigma,
            half_spread_bps=half_spread_bps,
            exchange_fee_bps=exchange_fee_bps,
        )
        multiplier = 2.0 if round_trip else 1.0
        cost_pct = cost.total_one_way_bps * multiplier / 100.0
        net = float(gross_alpha_pct) - cost_pct
        threshold = self.min_net_alpha_pct if min_net_alpha_pct is None else float(min_net_alpha_pct)
        accepted = net >= threshold
        reason = (
            f"순 기대 알파 {net:.2f}% >= 기준 {threshold:.2f}%"
            if accepted
            else f"순 기대 알파 {net:.2f}% < 기준 {threshold:.2f}%"
        )
        return NetAlphaAssessment(
            gross_alpha_pct=float(gross_alpha_pct),
            estimated_cost_pct=float(cost_pct),
            net_alpha_pct=float(net),
            accepted=accepted,
            reason=reason,
            cost=cost,
        )
