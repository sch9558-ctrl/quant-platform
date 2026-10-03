"""Four-slice TWAP/VWAP-style execution guidance."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json

DEFAULT_TIMES=("09:40","10:30","13:30","14:50")
DEFAULT_WEIGHTS=(.30,.20,.20,.30)

@dataclass(frozen=True)
class ExecutionSlice:
    time: str
    quantity: int
    limit_price: float
    share: float
    def to_dict(self): return asdict(self)

def build_execution_schedule(total_quantity:int, reference_price:float, *, side="BUY", times=DEFAULT_TIMES, weights=DEFAULT_WEIGHTS, limit_offsets_bps=(0,-5,-8,-3)):
    if total_quantity<=0 or reference_price<=0: raise ValueError("quantity and price must be positive")
    if len(times)!=len(weights) or len(times)!=len(limit_offsets_bps): raise ValueError("schedule dimensions differ")
    sw=sum(weights)
    if sw<=0: raise ValueError("weights must sum positive")
    weights=[w/sw for w in weights]
    raw=[total_quantity*w for w in weights]; qty=[int(x) for x in raw]
    for i in sorted(range(len(raw)),key=lambda i:raw[i]-qty[i],reverse=True)[:total_quantity-sum(qty)]: qty[i]+=1
    sign=1 if str(side).upper()=="BUY" else -1
    out=[]
    for t,q,w,bps in zip(times,qty,weights,limit_offsets_bps):
        price=reference_price*(1+sign*float(bps)/10000)
        out.append(ExecutionSlice(str(t),q,round(float(price),6),float(w)))
    return out

def write_execution_schedule(path, schedules):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({k:[x.to_dict() for x in v] for k,v in schedules.items()},ensure_ascii=False,indent=2),encoding="utf-8")
    return p
