"""Fama-French style residual alpha extraction via OLS."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ResidualAlphaResult:
    alpha_daily: float
    betas: dict[str,float]
    residuals: pd.Series
    cumulative_residual: pd.Series
    information_ratio: float
    def summary(self): return {"alpha_daily":self.alpha_daily,"betas":self.betas,"information_ratio":self.information_ratio}

def extract_residual_alpha(asset_returns,factors:pd.DataFrame,risk_free=0.0):
    y=pd.Series(asset_returns,dtype=float).rename("asset"); f=factors.astype(float).copy(); frame=pd.concat([y,f],axis=1).dropna()
    if len(frame)<max(10,len(f.columns)+2): raise ValueError("insufficient observations")
    rf=(pd.Series(risk_free,index=frame.index) if np.isscalar(risk_free) else pd.Series(risk_free).reindex(frame.index)).astype(float)
    yy=frame["asset"].to_numpy()-rf.to_numpy(); X=np.column_stack([np.ones(len(frame)),frame[f.columns].to_numpy()])
    coef=np.linalg.lstsq(X,yy,rcond=None)[0]; resid=yy-X@coef; residuals=pd.Series(resid,index=frame.index,name="residual")
    sd=float(residuals.std(ddof=1)); ir=float(residuals.mean()/sd*np.sqrt(252)) if sd>0 else 0.0
    return ResidualAlphaResult(float(coef[0]),{c:float(v) for c,v in zip(f.columns,coef[1:])},residuals,residuals.cumsum(),ir)

def top_residual_alpha_universe(results,percentile=.90):
    if not results:return []
    vals=pd.Series({k:v.information_ratio for k,v in results.items()}); cutoff=float(vals.quantile(percentile))
    return vals[vals>=cutoff].sort_values(ascending=False).index.tolist()
