"""Enterprise-style portfolio risk limits and kill switches."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import norm

@dataclass(frozen=True)
class GuardState:
    drawdown: float
    action: str
    allow_new_entries: bool
    liquidate_all: bool

class RiskGuard:
    def __init__(self,soft_stop:float=-0.05,hard_stop:float=-0.08,var_confidence:float=0.95):
        self.soft_stop=float(soft_stop); self.hard_stop=float(hard_stop); self.var_confidence=float(var_confidence)

    def parametric_var(self,returns:pd.DataFrame,weights:pd.Series,portfolio_value:float=1.0):
        R=returns.dropna(how="all").fillna(0.0); w=weights.reindex(R.columns).fillna(0).values
        mu=float(R.mean().values@w); sigma=float(np.sqrt(w@R.cov().values@w))
        loss=-(mu+norm.ppf(1-self.var_confidence)*sigma)*portfolio_value
        return float(max(loss,0.0))

    def historical_var(self,returns:pd.DataFrame,weights:pd.Series,portfolio_value:float=1.0):
        pnl=returns.fillna(0).dot(weights.reindex(returns.columns).fillna(0))
        return float(max(0.0,-np.quantile(pnl,1-self.var_confidence)*portfolio_value))

    def evaluate_drawdown(self,equity):
        s=pd.Series(equity,dtype=float).dropna()
        if s.empty:return GuardState(0.0,"NORMAL",True,False)
        dd=float(s.iloc[-1]/s.cummax().iloc[-1]-1)
        if dd<=self.hard_stop:return GuardState(dd,"HARD_KILL",False,True)
        if dd<=self.soft_stop:return GuardState(dd,"SOFT_STOP",False,False)
        return GuardState(dd,"NORMAL",True,False)

    @staticmethod
    def trailing_stop(highest_high:float,atr20:float,multiple:float=2.5):
        return float(highest_high-multiple*atr20)

    @staticmethod
    def should_exit_risk_reward(current_price:float,target_price:float,stop_price:float,min_rr:float=2.5):
        risk=max(current_price-stop_price,1e-12); reward=target_price-current_price
        return reward/risk<min_rr
