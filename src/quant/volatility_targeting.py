"""EWMA realized-volatility targeting with cash as the residual asset."""
from __future__ import annotations
from dataclasses import dataclass
import math
import pandas as pd

@dataclass(frozen=True)
class VolatilityTarget:
    realized_vol: float
    target_vol: float
    scale: float
    risky_weight: float
    cash_weight: float

class VolatilityTargeting:
    def __init__(self, target_vol: float=.12, span: int=20, max_scale: float=1.0, periods_per_year: int=252):
        if target_vol<=0 or span<2 or max_scale<=0: raise ValueError("invalid volatility targeting configuration")
        self.target_vol=float(target_vol); self.span=int(span); self.max_scale=float(max_scale); self.periods_per_year=int(periods_per_year)

    def realized_volatility(self, returns) -> float:
        s=pd.Series(returns,dtype=float).dropna()
        if len(s)<2: return 0.0
        ewma_var=s.ewm(span=self.span,adjust=False).var(bias=False).iloc[-1]
        if pd.isna(ewma_var) or ewma_var<0: return 0.0
        return float(math.sqrt(ewma_var*self.periods_per_year))

    def target(self, returns) -> VolatilityTarget:
        vol=self.realized_volatility(returns)
        scale=self.max_scale if vol<=0 else min(self.max_scale,self.target_vol/vol)
        risky=max(0.0,min(1.0,float(scale)))
        return VolatilityTarget(vol,self.target_vol,float(scale),risky,1.0-risky)
