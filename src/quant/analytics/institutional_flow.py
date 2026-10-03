"""Institutional/foreign flow and correlation crowding filters."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class FlowVerdict:
    status: str
    foreign_net: float
    institutional_net: float
    retail_net: float
    tradable: bool

def classify_krx_flow(flow:pd.DataFrame,lookback:int=5)->FlowVerdict:
    tail=flow.tail(int(lookback))
    f=float(pd.to_numeric(tail.get("foreign_net",0),errors="coerce").fillna(0).sum())
    i=float(pd.to_numeric(tail.get("institutional_net",0),errors="coerce").fillna(0).sum())
    r=float(pd.to_numeric(tail.get("retail_net",0),errors="coerce").fillna(0).sum())
    if f>0 and i>0: return FlowVerdict("DUAL_BUYING",f,i,r,True)
    if r>0 and f<0 and i<0: return FlowVerdict("TRAP_SUSPECTED",f,i,r,False)
    return FlowVerdict("MIXED",f,i,r,True)

def decorrelate_candidates(returns:pd.DataFrame,scores:pd.Series,threshold:float=0.65)->list[str]:
    ordered=scores.sort_values(ascending=False).index.tolist()
    corr=returns.reindex(columns=ordered).pct_change().corr() if (returns>0).all().all() else returns.reindex(columns=ordered).corr()
    kept=[]
    for sym in ordered:
        if all(pd.isna(corr.loc[sym,k]) or abs(float(corr.loc[sym,k]))<threshold for k in kept):
            kept.append(sym)
    return kept
