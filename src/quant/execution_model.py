"""Liquidity-aware execution cost and net-alpha filter."""
from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class ExecutionEstimate:
    impact_bps: float
    total_cost_bps: float
    net_expected_alpha: float
    accepted: bool

class ExecutionModel:
    def __init__(self,gamma:float=0.10,min_net_alpha:float=0.03):
        self.gamma=float(gamma); self.min_net_alpha=float(min_net_alpha)

    def estimate(self,order_notional:float,adv:float,sigma:float,half_spread_bps:float=5.0,
                 exchange_fee_bps:float=1.0,expected_alpha:float=0.0)->ExecutionEstimate:
        if order_notional<0 or adv<=0 or sigma<0: raise ValueError("invalid liquidity inputs")
        participation=max(order_notional/adv,0.0)
        # Requested AC-style square-root approximation. sigma is decimal daily volatility.
        impact_frac=self.gamma*float(sigma)*math.sqrt(participation)
        impact_bps=impact_frac*10000
        total_bps=impact_bps+float(half_spread_bps)+float(exchange_fee_bps)
        net=float(expected_alpha)-total_bps/10000
        return ExecutionEstimate(impact_bps,total_bps,net,net>=self.min_net_alpha)
