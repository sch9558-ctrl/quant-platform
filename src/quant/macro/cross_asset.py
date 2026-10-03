"""Cross-asset leading-risk filters for Korea and US."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class MacroRisk:
    market:str
    macro_risk_elevated:bool
    size_multiplier:float
    reasons:tuple[str,...]
    block_high_beta_growth:bool=False

def korea_macro_filter(usdkrw_return_1d:float,sox_return_1d:float,wti_return_5d:float|None=None)->MacroRisk:
    reasons=[]
    if usdkrw_return_1d>=0.008: reasons.append("원/달러 1일 +0.8% 이상 급등")
    if sox_return_1d<=-0.025: reasons.append("SOX 전일 -2.5% 이상 급락")
    return MacroRisk("korea",bool(reasons),0.5 if reasons else 1.0,tuple(reasons),False)

def us_macro_filter(vix:float,treasury10y_change_bp:float|None=None)->MacroRisk:
    reasons=[]; block=False
    if vix>25: reasons.append("VIX 25 초과"); block=True
    if treasury10y_change_bp is not None and treasury10y_change_bp>=15: reasons.append("미 10년물 금리 +15bp 이상")
    return MacroRisk("us",bool(reasons),0.5 if reasons else 1.0,tuple(reasons),block)

def collect_yahoo_macro(start,end):
    import yfinance as yf
    symbols={"usdkrw":"KRW=X","sox":"^SOX","wti":"CL=F","vix":"^VIX","ust10y":"^TNX"}
    out={}
    for key,ticker in symbols.items():
        try:
            df=yf.download(ticker,start=start,end=(pd.Timestamp(end)+pd.Timedelta(days=1)).strftime("%Y-%m-%d"),progress=False,auto_adjust=False)
            if df is not None and not df.empty: out[key]=df
        except Exception:
            continue
    return out
