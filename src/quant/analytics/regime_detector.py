"""Hurst-exponent regime classification."""
from __future__ import annotations
import numpy as np
import pandas as pd

def calculate_hurst_exponent(price_series:pd.Series,max_lags:int=100)->float:
    s=pd.Series(price_series,dtype=float).dropna()
    if len(s)<40:return 0.5
    logp=np.log(s[s>0])
    if len(logp)<40:return 0.5
    max_lags=min(int(max_lags),len(logp)//2)
    lags=np.arange(2,max(3,max_lags))
    tau=[]
    valid=[]
    for lag in lags:
        diff=logp.diff(lag).dropna()
        sd=float(diff.std(ddof=1))
        if sd>0: valid.append(lag); tau.append(sd)
    if len(tau)<3:return 0.5
    slope=np.polyfit(np.log(valid),np.log(tau),1)[0]
    return float(np.clip(slope,0,1))

def hurst_regime(price_series:pd.Series,max_lags:int=100)->dict:
    h=calculate_hurst_exponent(price_series,max_lags)
    mode="TREND" if h>0.55 else "MEAN_REVERSION" if h<0.45 else "NOISE"
    return {"hurst":h,"mode":mode,"tradable":mode!="NOISE"}
