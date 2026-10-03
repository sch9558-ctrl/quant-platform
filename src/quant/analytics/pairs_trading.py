"""Engle-Granger pair screening and spread z-score."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class PairSignal:
    beta:float
    pvalue:float
    zscore:float
    signal:str

def analyze_pair(price_a:pd.Series,price_b:pd.Series,window:int=90,entry_z:float=2.0)->PairSignal:
    from statsmodels.tsa.stattools import coint
    df=pd.concat([price_a.rename("a"),price_b.rename("b")],axis=1).dropna().tail(window)
    if len(df)<30: raise ValueError("insufficient pair history")
    _,pvalue,_=coint(np.log(df["a"]),np.log(df["b"]))
    X=np.column_stack([np.ones(len(df)),np.log(df["b"].values)])
    beta=np.linalg.lstsq(X,np.log(df["a"].values),rcond=None)[0]
    spread=np.log(df["a"])-(beta[0]+beta[1]*np.log(df["b"]))
    z=float((spread.iloc[-1]-spread.mean())/(spread.std(ddof=1) or 1e-12))
    signal="PAIRS_MEAN_REVERSION" if pvalue<0.05 and abs(z)>=entry_z else "NEUTRAL"
    return PairSignal(float(beta[1]),float(pvalue),z,signal)
