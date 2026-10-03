"""Korea 10-day customs nowcast parsing and HS-category signals."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

DEFAULT_HS_MAP={"memory_semiconductor":["854232"],"cosmetics":["3304"],"cathode_materials":["284290","382499"],"biopharma":["3002"],"power_equipment":["8504"]}

@dataclass(frozen=True)
class CustomsSignal:
    category:str
    yoy_growth:float
    signal:str
    representative_symbols:tuple[str,...]

def yoy_growth(current:float,prior_year_same_period:float)->float:
    if prior_year_same_period<=0:raise ValueError("prior-year value must be positive")
    return float(current/prior_year_same_period-1)

def detect_surprise_signals(rows:pd.DataFrame,symbol_map:dict[str,list[str]]|None=None,threshold:float=0.15):
    symbol_map=symbol_map or {}
    out=[]
    for _,row in rows.iterrows():
        category=str(row["category"])
        growth=yoy_growth(float(row["current_export"]),float(row["prior_export"]))
        if growth>threshold:
            out.append(CustomsSignal(category,growth,"EARNINGS_SURPRISE_EARLY_SIGNAL",tuple(symbol_map.get(category,[]))))
    return out
