"""Hurst-exponent regime detector using rescaled-range analysis."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class HurstRegime:
    hurst: float
    regime: str

def calculate_hurst_exponent(price_series,max_lags=100):
    s=pd.to_numeric(pd.Series(price_series),errors="coerce").dropna()
    if len(s)<32: raise ValueError("at least 32 prices required")
    returns=np.diff(np.log(s.to_numpy()));max_window=min(int(max_lags),len(returns)//2)
    sizes=np.unique(np.logspace(np.log10(8),np.log10(max_window),num=min(12,max_window-7)).astype(int));rs=[];valid=[]
    for n in sizes:
        vals=[]
        for j in range(len(returns)//n):
            seg=returns[j*n:(j+1)*n];dev=seg-seg.mean();z=np.cumsum(dev);R=z.max()-z.min();S=seg.std(ddof=1)
            if S>0 and R>0:vals.append(R/S)
        if vals:valid.append(n);rs.append(np.mean(vals))
    if len(rs)<2:return .5
    return float(np.clip(np.polyfit(np.log(valid),np.log(rs),1)[0],0,1))

def detect_hurst_regime(price_series,max_lags=100):
    h=calculate_hurst_exponent(price_series,max_lags)
    return HurstRegime(h,"MOMENTUM" if h>.55 else "MEAN_REVERSION" if h<.45 else "NOISE")
