"""Consensus target/estimate velocity and acceleration."""
from __future__ import annotations
import pandas as pd

def consensus_acceleration(history:pd.DataFrame,value_col:str="target_price",date_col:str="date",as_of=None)->dict:
    if history is None or history.empty:return {"velocity_30d":None,"acceleration_7d":None,"signal":"NO_DATA"}
    df=history[[date_col,value_col]].copy(); df[date_col]=pd.to_datetime(df[date_col]); df[value_col]=pd.to_numeric(df[value_col],errors="coerce")
    df=df.dropna().sort_values(date_col); end=pd.Timestamp(as_of or df[date_col].max())
    def mean_between(lo,hi):
        x=df[(df[date_col]>end-pd.Timedelta(days=lo))&(df[date_col]<=end-pd.Timedelta(days=hi))][value_col]
        return float(x.mean()) if len(x) else None
    cur=mean_between(30,0); old=mean_between(60,30)
    recent=mean_between(7,0); prior=mean_between(14,7); prior2=mean_between(21,14)
    velocity=(cur/old-1) if cur is not None and old not in (None,0) else None
    r1=(recent/prior-1) if recent is not None and prior not in (None,0) else None
    r0=(prior/prior2-1) if prior is not None and prior2 not in (None,0) else None
    accel=(r1-r0) if r1 is not None and r0 is not None else None
    signal="CONSENSUS_ACCELERATING" if velocity is not None and accel is not None and velocity>0 and accel>0 else "NEUTRAL"
    return {"velocity_30d":velocity,"acceleration_7d":accel,"signal":signal}
