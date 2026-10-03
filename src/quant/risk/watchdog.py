"""End-of-pipeline integrity watchdog and safe-mode verdict."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import pandas as pd

@dataclass(frozen=True)
class WatchdogResult:
    safe_mode: bool
    issues: tuple[str,...]
    discarded_report_indices: tuple[int,...]
    def to_dict(self): return asdict(self)

class QuantWatchdog:
    def __init__(self,max_price_jump_pct=30.0,max_sector_weight=.40,max_target_gap_pct=100.0):
        self.max_price_jump_pct=float(max_price_jump_pct); self.max_sector_weight=float(max_sector_weight); self.max_target_gap_pct=float(max_target_gap_pct)

    def inspect_prices(self, price_map):
        issues=[]
        for sym,obj in (price_map or {}).items():
            s=obj["close"] if isinstance(obj,pd.DataFrame) else pd.Series(obj)
            s=pd.to_numeric(s,errors="coerce")
            if (s<=0).any(): issues.append(f"NON_POSITIVE_PRICE:{sym}")
            jumps=s.pct_change().abs()*100
            if (jumps>self.max_price_jump_pct).any(): issues.append(f"PRICE_JUMP:{sym}")
        return issues

    def inspect_sector_weights(self, sector_weights):
        return [f"SECTOR_CONCENTRATION:{s}" for s,w in (sector_weights or {}).items() if float(w)>self.max_sector_weight]

    def inspect_reports(self,reports):
        bad=[]
        for i,r in enumerate(reports or []):
            target=r.get("target_price"); current=r.get("current_price") or r.get("start_price")
            if target in (None,0) or current in (None,0): continue
            gap=(float(target)/float(current)-1)*100
            if abs(gap)>self.max_target_gap_pct: bad.append(i)
        return bad

    def inspect(self, *, price_map=None, sector_weights=None, reports=None):
        issues=self.inspect_prices(price_map)+self.inspect_sector_weights(sector_weights)
        bad=self.inspect_reports(reports)
        if bad: issues.append(f"ABNORMAL_TARGET_REPORTS:{len(bad)}")
        return WatchdogResult(bool(issues),tuple(issues),tuple(bad))
