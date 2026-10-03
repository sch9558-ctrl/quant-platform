"""Metadata-only analyst report collectors."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date
import os, re
from typing import Iterable
import pandas as pd
import requests
from bs4 import BeautifulSoup

@dataclass
class AnalystReport:
    market:str; symbol:str; company:str|None; published_at:str; institution:str
    analyst:str|None; target_price:float|None; rating:str; currency:str; source:str
    source_url:str|None=None; previous_rating:str|None=None
    def to_dict(self): return asdict(self)

def normalize_rating(value)->str:
    t=str(value or "").strip().lower().replace(" ","")
    if any(k in t for k in ("strongbuy","buy","매수","outperform","overweight","accumulate","positive")): return "BUY"
    if any(k in t for k in ("sell","매도","underperform","underweight","negative","reduce")): return "SELL"
    if any(k in t for k in ("hold","neutral","보유","중립","marketperform","equalweight")): return "HOLD"
    return "UNKNOWN"

def _number(text):
    if text is None:return None
    m=re.search(r"(-?\d[\d,]*(?:\.\d+)?)",str(text))
    return float(m.group(1).replace(",","")) if m else None

class NaverResearchCollector:
    LIST_URL="https://finance.naver.com/research/company_list.naver"
    def __init__(self,timeout=15,session=None):
        self.timeout=timeout; self.session=session or requests.Session()
        self.session.headers.setdefault("User-Agent","Mozilla/5.0 quant-platform/1.0")
    @staticmethod
    def parse_detail(html):
        text=BeautifulSoup(html,"html.parser").get_text(" ",strip=True)
        tm=re.search(r"목표가\s*[:|]?\s*([\d,]+)",text)
        rm=re.search(r"투자의견\s*[:|]?\s*([A-Za-z가-힣 /+-]+?)(?=\s{2,}|목표가|작성일|$)",text)
        return (_number(tm.group(1)) if tm else None, normalize_rating(rm.group(1) if rm else ""))
    @staticmethod
    def parse_list(html):
        soup=BeautifulSoup(html,"html.parser"); out=[]
        for row in soup.select("tr"):
            detail=row.find("a",href=re.compile(r"company_read\.naver"))
            if not detail: continue
            cells=[c.get_text(" ",strip=True) for c in row.find_all("td")]
            item=row.find("a",href=re.compile(r"code=\d{6}"))
            href=detail.get("href",""); symbol=None
            for h in ((item.get("href","") if item else ""),href):
                m=re.search(r"code=(\d{6})",h)
                if m: symbol=m.group(1); break
            dm=re.search(r"\d{2}\.\d{2}\.\d{2}|\d{4}[.-]\d{2}[.-]\d{2}"," ".join(cells))
            published=dm.group(0) if dm else None
            if published:
                published=published.replace(".","-")
                if len(published.split("-")[0])==2: published="20"+published
            out.append({"symbol":symbol,"company":item.get_text(" ",strip=True) if item else (cells[0] if cells else None),"institution":cells[-2] if len(cells)>=2 else "미상","analyst":None,"published_at":published,"detail_url":requests.compat.urljoin("https://finance.naver.com",href)})
        return out
    def collect(self,symbols:Iterable[str]|None=None,max_pages=3):
        wanted={str(s) for s in symbols} if symbols else None; out=[]
        for page in range(1,max_pages+1):
            r=self.session.get(self.LIST_URL,params={"page":page},timeout=self.timeout); r.raise_for_status()
            rows=self.parse_list(r.text)
            if not rows:break
            for row in rows:
                if not row["symbol"] or not row["published_at"] or (wanted is not None and row["symbol"] not in wanted):continue
                try:
                    d=self.session.get(row["detail_url"],timeout=self.timeout); d.raise_for_status()
                    target,rating=self.parse_detail(d.text)
                except Exception: target,rating=None,"UNKNOWN"
                out.append(AnalystReport("korea",row["symbol"],row["company"],row["published_at"],row["institution"],row["analyst"],target,rating,"KRW","naver_finance",row["detail_url"]))
        return out

class YahooAnalystCollector:
    def collect(self,symbols):
        import yfinance as yf
        out=[]; today=str(pd.Timestamp.now(tz="UTC").date())
        for symbol in symbols:
            t=yf.Ticker(symbol)
            try:
                ud=t.get_upgrades_downgrades()
                if ud is not None and not ud.empty:
                    for idx,row in ud.head(100).iterrows():
                        out.append(AnalystReport("us",symbol,None,str(pd.Timestamp(idx).date()),str(row.get("Firm") or row.get("firm") or "Unknown"),None,None,normalize_rating(row.get("ToGrade") or row.get("toGrade")),"USD","yahoo_finance",f"https://finance.yahoo.com/quote/{symbol}/analysis/",normalize_rating(row.get("FromGrade") or row.get("fromGrade"))))
            except Exception: pass
            try:
                targets=t.get_analyst_price_targets()
                if isinstance(targets,dict):
                    target=targets.get("mean") or targets.get("meanPrice") or targets.get("targetMeanPrice")
                    if target: out.append(AnalystReport("us",symbol,None,today,"Yahoo Finance Consensus",None,float(target),"UNKNOWN","USD","yahoo_finance_consensus",f"https://finance.yahoo.com/quote/{symbol}/analysis/"))
            except Exception: pass
        return out

class FinnhubAnalystCollector:
    BASE="https://finnhub.io/api/v1"
    def __init__(self,token=None,timeout=15): self.token=token or os.getenv("FINNHUB_API_KEY",""); self.timeout=timeout
    def collect(self,symbols,start=None,end=None):
        if not self.token:return []
        end=end or str(date.today()); start=start or str((pd.Timestamp(end)-pd.DateOffset(years=2)).date()); out=[]
        for symbol in symbols:
            try:
                r=requests.get(self.BASE+"/stock/upgrade-downgrade",params={"symbol":symbol,"from":start,"to":end,"token":self.token},timeout=self.timeout); r.raise_for_status()
                for row in r.json() or []:
                    published=pd.to_datetime(row.get("gradeTime"),unit="s",errors="coerce")
                    if pd.isna(published):continue
                    out.append(AnalystReport("us",symbol,None,str(published.date()),str(row.get("company") or "Unknown"),None,None,normalize_rating(row.get("toGrade")),"USD","finnhub",None,normalize_rating(row.get("fromGrade"))))
            except Exception: continue
        return out

class CSVReportCollector:
    def collect_file(self,path):
        df=pd.read_csv(path); required={"market","symbol","published_at","institution","rating","currency","source"}
        missing=required-set(df.columns)
        if missing: raise ValueError(f"missing report columns: {sorted(missing)}")
        out=[]
        for _,r in df.iterrows():
            out.append(AnalystReport(str(r["market"]),str(r["symbol"]),None if pd.isna(r.get("company")) else str(r.get("company")),str(pd.Timestamp(r["published_at"]).date()),str(r["institution"]),None if pd.isna(r.get("analyst")) else str(r.get("analyst")),None if pd.isna(r.get("target_price")) else float(r.get("target_price")),normalize_rating(r.get("rating")),str(r["currency"]),str(r["source"]),None if pd.isna(r.get("source_url")) else str(r.get("source_url"))))
        return out
