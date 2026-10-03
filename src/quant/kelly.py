"""Conservative dynamic Kelly position sizing."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class KellySizing:
    full_kelly:float
    applied_fraction:float
    portfolio_weight:float

def dynamic_kelly(win_probability,win_loss_ratio,*,fraction=.25,max_weight=.10,confidence=1.0):
    p=max(0.,min(1.,float(win_probability)));b=float(win_loss_ratio)
    if b<=0:return KellySizing(0.,float(fraction),0.)
    q=1-p;full=max(0.,(b*p-q)/b);confidence=max(0.,min(1.,float(confidence)));weight=min(float(max_weight),full*float(fraction)*confidence)
    return KellySizing(full,float(fraction),max(0.,weight))
