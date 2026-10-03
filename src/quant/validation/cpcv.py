"""Purged/embargoed time-series CV and robust backtest statistics."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis

def purged_embargo_splits(n_samples:int,n_splits:int=5,purge:int=5,embargo:int=5):
    if n_samples<=0 or n_splits<2: raise ValueError("invalid split parameters")
    indices=np.arange(n_samples)
    blocks=np.array_split(indices,n_splits)
    out=[]
    for test in blocks:
        lo=max(0,int(test[0])-purge); hi=min(n_samples,int(test[-1])+1+embargo)
        train=indices[(indices<lo)|(indices>=hi)]
        out.append((train,test))
    return out

def max_drawdown_and_recovery(returns:pd.Series):
    equity=(1+pd.Series(returns,dtype=float).fillna(0)).cumprod()
    peak=equity.cummax(); dd=equity/peak-1
    if dd.empty: return 0.0,0
    trough=dd.idxmin(); mdd=float(dd.min()); peak_val=float(peak.loc[trough])
    after=equity.loc[trough:]
    recovered=after[after>=peak_val]
    recovery=int(after.index.get_loc(recovered.index[0])) if len(recovered) else None
    return mdd,recovery

def profit_factor(returns):
    r=pd.Series(returns,dtype=float).dropna(); gains=r[r>0].sum(); losses=-r[r<0].sum()
    return float(gains/losses) if losses>0 else float("inf") if gains>0 else 0.0

def calmar_ratio(returns,periods_per_year:int=252):
    r=pd.Series(returns,dtype=float).dropna()
    if r.empty:return 0.0
    years=max(len(r)/periods_per_year,1/periods_per_year)
    cagr=float((1+r).prod()**(1/years)-1)
    mdd,_=max_drawdown_and_recovery(r)
    return float(cagr/abs(mdd)) if mdd<0 else float("inf")

def deflated_sharpe_ratio(returns,n_trials:int=1,periods_per_year:int=252):
    r=pd.Series(returns,dtype=float).dropna()
    if len(r)<3 or r.std(ddof=1)==0:return 0.0
    sr=float(r.mean()/r.std(ddof=1)*math.sqrt(periods_per_year))
    # Bailey/Lopez-de-Prado style variance adjustment + multiple-testing expected maximum.
    sr_var=(1+0.5*sr**2-float(skew(r))*sr+((float(kurtosis(r,fisher=False))-3)/4)*sr**2)/max(len(r)-1,1)
    expected_max=0.0 if n_trials<=1 else norm.ppf(1-1/max(n_trials,2))/math.sqrt(periods_per_year)
    z=(sr-expected_max)/math.sqrt(max(sr_var,1e-12))
    return float(norm.cdf(z))
