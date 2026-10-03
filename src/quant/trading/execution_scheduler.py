"""Four-slice TWAP/VWAP execution guidance generator."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from pathlib import Path
import json

TIMES=("09:40","10:30","13:30","14:50")
DEFAULT_WEIGHTS=(0.30,0.20,0.20,0.30)

@dataclass(frozen=True)
class Slice:
    time:str
    quantity:int
    limit_price:float

def build_execution_schedule(total_quantity:int,entry_low:float,entry_high:float,weights=DEFAULT_WEIGHTS):
    if total_quantity<0 or entry_low<=0 or entry_high<entry_low: raise ValueError("invalid schedule inputs")
    raw=[int(total_quantity*w) for w in weights]; rem=total_quantity-sum(raw)
    for i in range(rem): raw[i%len(raw)]+=1
    midpoint=(entry_low+entry_high)/2
    prices=[entry_low,midpoint,midpoint,entry_high]
    return [Slice(t,q,float(p)) for t,q,p in zip(TIMES,raw,prices) if q>0]

def write_execution_schedule(rows,path="dashboard/data/execution_schedule.json"):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    payload=[asdict(x) if hasattr(x,"__dataclass_fields__") else x for x in rows]
    p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); return p
