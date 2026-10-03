"""Customs 10-day export nowcasting normalization and equity signal mapping."""
from __future__ import annotations
from dataclasses import asdict,dataclass

DEFAULT_HS_MAP={"memory_semiconductor":["854232"],"cosmetics":["3304"],"cathode_material":["284290","382499"],"biopharma":["3002"],"power_equipment":["8504"]}

@dataclass(frozen=True)
class CustomsSignal:
    category:str
    hs_code:str
    yoy_pct:float
    symbols:tuple[str,...]
    flag:str
    def to_dict(self):return asdict(self)

def yoy_growth(current,prior):return None if prior in (None,0) else (float(current)/float(prior)-1)*100

def generate_customs_signals(rows,symbol_map,*,threshold_pct=15.0):
    out=[]
    for row in rows:
        y=yoy_growth(row.get("current_export"),row.get("prior_year_export"))
        if y is None or y<=threshold_pct:continue
        hs=str(row.get("hs_code",""));category=str(row.get("category") or hs);symbols=tuple(symbol_map.get(category) or symbol_map.get(hs) or [])
        if symbols:out.append(CustomsSignal(category,hs,float(y),symbols,"EARNINGS_SURPRISE_EARLY_SIGNAL"))
    return out
