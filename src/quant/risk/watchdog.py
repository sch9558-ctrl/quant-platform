"""Final integrity watchdog before signals become actionable."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class WatchdogResult:
    safe_mode:bool
    issues:tuple[str,...]

def inspect_watchdog(price_rows:pd.DataFrame|None,sector_weights:dict[str,float]|None,target_gaps_pct:list[float]|None)->WatchdogResult:
    issues=[]
    if price_rows is not None and not price_rows.empty:
        for col in ("open","high","low","close"):
            if col in price_rows and (pd.to_numeric(price_rows[col],errors="coerce")<=0).any(): issues.append("NON_POSITIVE_PRICE")
        if "return_1d" in price_rows and (pd.to_numeric(price_rows["return_1d"],errors="coerce").abs()>0.30).any(): issues.append("PRICE_JUMP_GT_30PCT")
    if sector_weights and max(sector_weights.values(),default=0)>0.40: issues.append("SECTOR_WEIGHT_GT_40PCT")
    if target_gaps_pct and any(abs(float(x))>100 for x in target_gaps_pct if x is not None): issues.append("TARGET_GAP_GT_100PCT")
    return WatchdogResult(bool(issues),tuple(sorted(set(issues))))
