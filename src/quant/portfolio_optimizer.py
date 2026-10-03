"""Black-Litterman allocation with long-only institutional constraints."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.optimize import minimize

@dataclass(frozen=True)
class BLResult:
    posterior_returns: pd.Series
    posterior_cov: pd.DataFrame
    weights: pd.Series
    cash_weight: float

class BlackLittermanOptimizer:
    def __init__(self, risk_aversion: float=2.5, tau: float=0.05, max_weight: float=0.10):
        self.risk_aversion=float(risk_aversion); self.tau=float(tau); self.max_weight=float(max_weight)

    def implied_equilibrium_returns(self, cov: pd.DataFrame, market_weights: pd.Series) -> pd.Series:
        w=market_weights.reindex(cov.index).fillna(0.0).astype(float)
        if w.sum()<=0: raise ValueError("market_weights must have positive mass")
        w=w/w.sum()
        return pd.Series(self.risk_aversion*(cov.values@w.values),index=cov.index,name="prior")

    def posterior(self, cov: pd.DataFrame, prior: pd.Series, P, Q, omega=None):
        s=cov.astype(float); pi=prior.reindex(s.index).astype(float).values
        P=np.asarray(P,dtype=float); Q=np.asarray(Q,dtype=float).reshape(-1)
        if P.ndim!=2 or P.shape[1]!=len(s) or P.shape[0]!=len(Q): raise ValueError("invalid P/Q dimensions")
        tauS=self.tau*s.values
        O=np.diag(np.diag(P@tauS@P.T)) if omega is None else np.asarray(omega,dtype=float)
        middle=np.linalg.pinv(P@tauS@P.T+O)
        mu=pi+tauS@P.T@middle@(Q-P@pi)
        post_cov=s.values+tauS-tauS@P.T@middle@P@tauS
        return pd.Series(mu,index=s.index,name="posterior_return"),pd.DataFrame(post_cov,index=s.index,columns=s.columns)

    @staticmethod
    def omega_from_credibility(view_variances, credibility):
        v=np.asarray(view_variances,dtype=float); c=np.clip(np.asarray(credibility,dtype=float),0.01,1.0)
        return np.diag(v/c)

    def optimize(self, expected: pd.Series, cov: pd.DataFrame, sectors: dict[str,str]|None=None,
                 benchmark_sector_weights: dict[str,float]|None=None, sector_band: float=0.05) -> pd.Series:
        idx=list(expected.index); mu=expected.astype(float).values; S=cov.reindex(index=idx,columns=idx).astype(float).values
        n=len(idx); x0=np.full(n,min(self.max_weight,1/max(n,1))*0.95)
        constraints=[{"type":"ineq","fun":lambda w:1.0-w.sum()}]
        sectors=sectors or {}; benchmark_sector_weights=benchmark_sector_weights or {}
        for sec,bw in benchmark_sector_weights.items():
            ids=np.array([i for i,s in enumerate(idx) if sectors.get(s)==sec],dtype=int)
            if len(ids):
                lo=max(0.0,float(bw)-sector_band); hi=min(1.0,float(bw)+sector_band)
                constraints += [
                    {"type":"ineq","fun":lambda w,ids=ids,lo=lo:w[ids].sum()-lo},
                    {"type":"ineq","fun":lambda w,ids=ids,hi=hi:hi-w[ids].sum()},
                ]
        def obj(w): return -(w@mu-0.5*self.risk_aversion*(w@S@w))
        res=minimize(obj,x0,bounds=[(0,self.max_weight)]*n,constraints=constraints,method="SLSQP",
                     options={"maxiter":500,"ftol":1e-10})
        if not res.success: raise RuntimeError(f"allocation optimization failed: {res.message}")
        return pd.Series(np.clip(res.x,0,self.max_weight),index=idx,name="weight")

    def run(self, cov, market_weights, P, Q, omega=None, **opt_kwargs):
        prior=self.implied_equilibrium_returns(cov,market_weights)
        mu,post_cov=self.posterior(cov,prior,P,Q,omega)
        w=self.optimize(mu,post_cov,**opt_kwargs)
        return BLResult(mu,post_cov,w,float(max(0.0,1-w.sum())))
