"""Fama-French style residual alpha extraction without external regressors."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class ResidualAlphaResult:
    alpha: float
    betas: pd.Series
    residuals: pd.Series
    cumulative_residual: pd.Series
    information_ratio: float

def fit_residual_alpha(asset_returns:pd.Series,factors:pd.DataFrame,risk_free:pd.Series|float=0.0)->ResidualAlphaResult:
    y=pd.Series(asset_returns,dtype=float)
    rf=pd.Series(float(risk_free),index=y.index) if np.isscalar(risk_free) else pd.Series(risk_free,dtype=float)
    frame=pd.concat([y.rename("asset"),rf.rename("rf"),factors.astype(float)],axis=1).dropna()
    if len(frame)<=len(factors.columns)+2: raise ValueError("insufficient observations")
    yv=(frame["asset"]-frame["rf"]).values
    X=np.column_stack([np.ones(len(frame)),frame[factors.columns].values])
    beta=np.linalg.lstsq(X,yv,rcond=None)[0]; fitted=X@beta; resid=yv-fitted
    residuals=pd.Series(resid,index=frame.index,name="residual")
    ir=float(residuals.mean()/residuals.std(ddof=1)*np.sqrt(252)) if residuals.std(ddof=1)>0 else 0.0
    return ResidualAlphaResult(float(beta[0]),pd.Series(beta[1:],index=factors.columns),residuals,residuals.cumsum(),ir)

def top_residual_alpha(results:dict[str,ResidualAlphaResult],quantile:float=0.90)->list[str]:
    if not results:return []
    s=pd.Series({k:v.information_ratio for k,v in results.items()})
    cutoff=float(s.quantile(quantile))
    return s[s>=cutoff].sort_values(ascending=False).index.tolist()
