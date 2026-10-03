"""Engle-Granger-style pair screening and spread Z-score."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import math,numpy as np,pandas as pd

@dataclass(frozen=True)
class PairSignal:
    beta:float
    adf_t_stat:float
    cointegrated:bool
    zscore:float
    signal:str
    def to_dict(self):return asdict(self)

def _adf0_tstat(residual):
    e=np.asarray(residual,dtype=float);de=np.diff(e);lag=e[:-1];X=np.column_stack([np.ones(len(lag)),lag])
    coef=np.linalg.lstsq(X,de,rcond=None)[0];err=de-X@coef;dof=max(len(de)-2,1);s2=float(err@err/dof);cov=s2*np.linalg.pinv(X.T@X);se=math.sqrt(max(cov[1,1],1e-18))
    return float(coef[1]/se)

def analyze_pair(a,b,lookback=90,z_threshold=2.0,adf_critical=-3.34):
    x=pd.to_numeric(pd.Series(a),errors="coerce");y=pd.to_numeric(pd.Series(b),errors="coerce");frame=pd.concat([x.rename("x"),y.rename("y")],axis=1).dropna().tail(int(lookback))
    if len(frame)<30:raise ValueError("at least 30 aligned observations required")
    X=np.column_stack([np.ones(len(frame)),frame["x"].to_numpy()]);coef=np.linalg.lstsq(X,frame["y"].to_numpy(),rcond=None)[0]
    beta=float(coef[1]);spread=frame["y"]-(coef[0]+beta*frame["x"]);t=_adf0_tstat(spread.to_numpy());sd=float(spread.std(ddof=1));z=float((spread.iloc[-1]-spread.mean())/sd) if sd>0 else 0.
    coint=t<float(adf_critical);signal="PAIRS_MEAN_REVERSION" if coint and abs(z)>=float(z_threshold) else "NONE"
    return PairSignal(beta,t,coint,z,signal)
