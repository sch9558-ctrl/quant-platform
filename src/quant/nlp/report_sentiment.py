"""Report/call conviction analysis with optional external LLM scorer."""
from __future__ import annotations
from dataclasses import dataclass

HEDGES=("불확실","보수적","도전적","단기 변동성","리스크","uncertain","challenging","cautious","volatility")
POSITIVE=("강력","확신","가속","상향","호조","surprise","strong","accelerat","upside","confident")

@dataclass(frozen=True)
class SentimentResult:
    conviction_score:float
    hedge_count:int
    evasive_flag:bool
    stealth_downgrade:bool
    method:str

def analyze_report(text:str,target_raised:bool=False,llm_scorer=None)->SentimentResult:
    if llm_scorer is not None:
        score=float(llm_scorer(text)); method="external_llm"
    else:
        lower=text.lower()
        pos=sum(lower.count(x.lower()) for x in POSITIVE)
        neg=sum(lower.count(x.lower()) for x in HEDGES)
        score=max(0.0,min(100.0,50+8*pos-10*neg))
        method="lexicon_fallback"
    hedge=sum(text.lower().count(x.lower()) for x in HEDGES)
    return SentimentResult(score,hedge,hedge>=2,bool(target_raised and score<40),method)
