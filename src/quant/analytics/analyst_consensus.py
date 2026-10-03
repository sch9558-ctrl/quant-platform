"""Analyst target-price accuracy and credibility analytics."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Iterable
import numpy as np
import pandas as pd

HORIZONS={"1m":21,"3m":63,"6m":126,"1y":252}

@dataclass
class ReportEvaluation:
    source:str; market:str; symbol:str; institution:str; analyst:str|None; published_at:str
    rating:str; target_price:float|None; start_price:float|None; horizon:str
    hit:bool|None; sessions_to_hit:int|None; max_high:float|None; min_low:float|None
    end_return_pct:float|None; disparity_pct:float|None
    def to_dict(self): return asdict(self)

def _window(prices,published_at,sessions):
    if prices is None or prices.empty: return None,None
    p=prices.copy().sort_index(); p.index=pd.DatetimeIndex(pd.to_datetime(p.index)).tz_localize(None)
    dt=pd.Timestamp(published_at); dt=dt.tz_localize(None) if dt.tzinfo else dt
    eligible=p.loc[p.index>=dt.normalize()]
    return (None,None) if eligible.empty else (eligible.iloc[0],eligible.iloc[:sessions+1])

class AnalystTracker:
    def evaluate_report(self,report,prices):
        out=[]
        for horizon,sessions in HORIZONS.items():
            first,w=_window(prices,report.published_at,sessions)
            start=float(first["close"]) if first is not None and pd.notna(first.get("close")) else None
            target=float(report.target_price) if report.target_price is not None else None
            hit=days=max_high=min_low=end_return=disparity=None
            if w is not None and not w.empty and start is not None:
                high=pd.to_numeric(w["high"],errors="coerce"); low=pd.to_numeric(w["low"],errors="coerce")
                max_high=float(high.max()); min_low=float(low.min()); end_close=float(pd.to_numeric(w["close"],errors="coerce").iloc[-1])
                end_return=(end_close/start-1)*100
                if target is not None and target>0:
                    disparity=(target-max_high)/target*100
                    bearish=report.rating=="SELL" or target<start
                    mask=(low<=target) if bearish else (high>=target)
                    hit=bool(mask.any())
                    if hit: days=int(np.flatnonzero(mask.to_numpy())[0])
            out.append(ReportEvaluation(report.source,report.market,report.symbol,report.institution,report.analyst,str(pd.Timestamp(report.published_at).date()),report.rating,target,start,horizon,hit,days,max_high,min_low,end_return,disparity))
        return out
    @staticmethod
    def credibility(rows:Iterable[ReportEvaluation],horizon="3m"):
        chosen=[r for r in rows if r.horizon==horizon]; targets=[r for r in chosen if r.hit is not None]
        hit_rate=float(np.mean([r.hit for r in targets])) if targets else 0.0
        bearish=[r for r in chosen if r.rating=="SELL" and r.end_return_pct is not None]
        downside=float(np.mean([r.end_return_pct<0 for r in bearish])) if bearish else .5
        disparities=[abs(r.disparity_pct) for r in targets if r.disparity_pct is not None]
        stability=max(0.0,1-float(np.median(disparities))/100) if disparities else .5
        score=round(min(max((hit_rate*.5+downside*.2+stability*.3)*100,0),100),2)
        tier="S" if score>=85 else "A" if score>=70 else "B" if score>=55 else "C"
        return {"horizon":horizon,"n_reports":len(chosen),"n_target_reports":len(targets),"hit_rate":round(hit_rate,4),"downside_foresight":round(downside,4),"disparity_stability":round(stability,4),"credibility_score":score,"tier":tier}
    def aggregate(self,evaluations):
        rows=list(evaluations); firms={}; analysts={}
        for r in rows:
            firms.setdefault(r.institution or "Unknown",[]).append(r)
            if r.analyst: analysts.setdefault(r.analyst,[]).append(r)
        fi=[{"institution":k,**self.credibility(v)} for k,v in firms.items()]
        an=[{"analyst":k,**self.credibility(v)} for k,v in analysts.items()]
        fi.sort(key=lambda x:(-x["credibility_score"],-x["n_reports"],x["institution"]))
        an.sort(key=lambda x:(-x["credibility_score"],-x["n_reports"],x["analyst"]))
        return {"overall":self.credibility(rows),"institutions":fi,"analysts":an}
