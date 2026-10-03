"""Consensus estimate velocity and second-difference acceleration."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import pandas as pd

@dataclass(frozen=True)
class ConsensusAcceleration:
    velocity_30d: float
    recent_7d_change: float
    prior_7d_change: float
    acceleration: float
    label: str
    def to_dict(self): return asdict(self)

def _pct(a,b):
    return 0.0 if b in (None,0) else float(a/b-1.0)

def measure_consensus_acceleration(series) -> ConsensusAcceleration:
    s=pd.Series(series,dtype=float)
    if isinstance(series,pd.Series) and isinstance(series.index,pd.DatetimeIndex): s.index=series.index
    s=s.dropna()
    if len(s)<2: return ConsensusAcceleration(0,0,0,0,"INSUFFICIENT_DATA")
    if isinstance(s.index,pd.DatetimeIndex):
        end=s.index.max()
        def at_or_before(days):
            z=s.loc[s.index<=end-pd.Timedelta(days=days)]
            return float(z.iloc[-1]) if len(z) else float(s.iloc[0])
        now=float(s.iloc[-1]); d7=at_or_before(7); d14=at_or_before(14); d30=at_or_before(30)
    else:
        now=float(s.iloc[-1]); d7=float(s.iloc[max(0,len(s)-8)]); d14=float(s.iloc[max(0,len(s)-15)]); d30=float(s.iloc[max(0,len(s)-31)])
    recent=_pct(now,d7); prior=_pct(d7,d14); velocity=_pct(now,d30); accel=recent-prior
    label="CONSENSUS_ACCELERATING" if velocity>0 and accel>0 else "DECELERATING" if accel<0 else "NEUTRAL"
    return ConsensusAcceleration(velocity,recent,prior,accel,label)
