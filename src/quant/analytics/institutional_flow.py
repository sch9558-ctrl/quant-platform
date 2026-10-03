"""Institutional/foreign flow validation and portfolio de-correlation."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import pandas as pd

@dataclass(frozen=True)
class FlowAssessment:
    status: str
    foreign_net: float
    institutional_net: float
    retail_net: float
    buy_allowed: bool
    def to_dict(self): return asdict(self)

def assess_krx_flow(flow_df, lookback=5):
    if flow_df is None or flow_df.empty: return FlowAssessment("UNKNOWN",0.0,0.0,0.0,False)
    tail=flow_df.tail(max(1,int(lookback)))
    f=float(pd.to_numeric(tail.get("foreign",0),errors="coerce").fillna(0).sum())
    i=float(pd.to_numeric(tail.get("institutional",0),errors="coerce").fillna(0).sum())
    r=float(pd.to_numeric(tail.get("retail",0),errors="coerce").fillna(0).sum())
    if f>0 and i>0: return FlowAssessment("DOUBLE_BUY",f,i,r,True)
    if f<0 and i<0 and r>0: return FlowAssessment("TRAP_SUSPECTED",f,i,r,False)
    return FlowAssessment("MIXED",f,i,r,True)

@dataclass(frozen=True)
class DecorrelationResult:
    kept: tuple[str,...]
    dropped: tuple[str,...]
    correlation: pd.DataFrame

def decorrelate_candidates(price_map, scores, *, threshold=.65, lookback=60):
    returns={}
    for symbol,obj in price_map.items():
        s=obj["close"] if isinstance(obj,pd.DataFrame) else obj
        s=pd.to_numeric(s,errors="coerce").dropna().tail(lookback+1)
        if len(s)>=3: returns[symbol]=s.pct_change().dropna().reset_index(drop=True)
    if not returns: return DecorrelationResult(tuple(),tuple(),pd.DataFrame())
    frame=pd.DataFrame(returns); corr=frame.corr()
    ordered=sorted(frame.columns,key=lambda s:float(scores.get(s,0.0)),reverse=True); kept=[]; dropped=[]
    for symbol in ordered:
        if any(abs(float(corr.loc[symbol,k]))>=threshold for k in kept if pd.notna(corr.loc[symbol,k])): dropped.append(symbol)
        else: kept.append(symbol)
    return DecorrelationResult(tuple(kept),tuple(dropped),corr)
