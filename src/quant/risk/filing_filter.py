"""DART/SEC filing metadata risk keyword filter.

Network collection is intentionally separated from classification so CI can
test deterministic filing records and production can feed DART/EDGAR JSON.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
import os
import pandas as pd
import requests

RISK_TERMS=("유상증자","전환사채","신주인수권부사채","CB","BW","최대주주","감사의견 거절","한정의견",
            "going concern","convertible notes","registered direct offering","dilution","material weakness")

@dataclass(frozen=True)
class FilingRisk:
    risk_cleared: bool
    matched_terms: tuple[str,...]
    matched_filings: tuple[str,...]

def classify_filings(filings,as_of=None,lookback_days:int=14)->FilingRisk:
    end=pd.Timestamp(as_of or pd.Timestamp.now(tz="UTC")).tz_localize(None).normalize()
    start=end-pd.Timedelta(days=int(lookback_days)); terms=set(); names=[]
    for row in filings or []:
        d=pd.Timestamp(row.get("date") or row.get("filed_at") or row.get("rcept_dt")).tz_localize(None).normalize()
        if not (start<=d<=end):continue
        text=" ".join(str(row.get(k,"")) for k in ("title","report_name","form","description","text"))
        hit=[t for t in RISK_TERMS if t.lower() in text.lower()]
        if hit: terms.update(hit); names.append(str(row.get("title") or row.get("report_name") or row.get("form") or "filing"))
    return FilingRisk(not bool(terms),tuple(sorted(terms)),tuple(names))

class FilingClient:
    def __init__(self,dart_key:str|None=None,sec_user_agent:str|None=None,timeout:int=15):
        self.dart_key=dart_key or os.getenv("DART_API_KEY","")
        self.sec_user_agent=sec_user_agent or os.getenv("SEC_USER_AGENT","quant-platform research contact@example.com")
        self.timeout=timeout
    def dart_recent(self,corp_code:str,bgn_de:str,end_de:str):
        if not self.dart_key:return []
        r=requests.get("https://opendart.fss.or.kr/api/list.json",params={"crtfc_key":self.dart_key,"corp_code":corp_code,"bgn_de":bgn_de,"end_de":end_de,"page_count":100},timeout=self.timeout)
        r.raise_for_status(); return r.json().get("list",[]) or []
    def sec_recent(self,cik:str):
        cik=str(cik).zfill(10)
        r=requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",headers={"User-Agent":self.sec_user_agent},timeout=self.timeout)
        r.raise_for_status(); data=r.json(); recent=(data.get("filings") or {}).get("recent") or {}
        forms=recent.get("form",[]); dates=recent.get("filingDate",[]); desc=recent.get("primaryDocument",[])
        return [{"date":d,"form":f,"description":p} for f,d,p in zip(forms,dates,desc)]
