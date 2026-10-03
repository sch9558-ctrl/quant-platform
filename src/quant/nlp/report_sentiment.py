"""Transparent lexical conviction/evasiveness scorer for report/call text."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import re
POS=("확신","상향","강한 성장","가시성","record","strong demand","confident","raise","beat","accelerat")
HEDGE=("불확실","보수적 접근","도전적","단기 변동성","가시성 제한","uncertain","challenging","cautious","volatility","headwind","visibility remains limited")

@dataclass(frozen=True)
class ReportSentiment:
    conviction_score:int
    hedge_count:int
    positive_count:int
    evasive_flag:bool
    stealth_downgrade:bool
    def to_dict(self):return asdict(self)

def analyze_report_text(text,target_raised=False):
    t=str(text or "").lower();pos=sum(len(re.findall(re.escape(x.lower()),t)) for x in POS);hedge=sum(len(re.findall(re.escape(x.lower()),t)) for x in HEDGE)
    tokens=max(len(t.split()),1);density=min(1.,(pos+hedge)/(tokens/20+1));raw=50+12*pos-14*hedge;score=int(round(max(0,min(100,50+(raw-50)*max(.35,density)))))
    evasive=hedge>=2 and hedge>pos
    return ReportSentiment(score,hedge,pos,evasive,bool(target_raised and score<40))
