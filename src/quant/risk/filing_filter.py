"""Recent filing risk filter for KRX (DART) and US (SEC EDGAR)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import re

import pandas as pd


RISK_PATTERNS = {
    "equity_dilution": [
        r"유상증자", r"제3자배정", r"rights offering", r"secondary offering",
        r"public offering", r"registered direct offering",
    ],
    "convertible_financing": [
        r"전환사채", r"신주인수권부사채", r"\bCB\b", r"\bBW\b",
        r"convertible note", r"convertible debt",
    ],
    "controlling_holder_sale": [
        r"최대주주.{0,20}(매도|처분|감소)", r"major shareholder.{0,30}(sale|sell|dispos)",
        r"principal shareholder.{0,30}(sale|sell)",
    ],
    "audit_warning": [
        r"감사의견.{0,10}(거절|한정)", r"의견거절", r"한정의견",
        r"qualified opinion", r"adverse opinion", r"disclaimer of opinion",
        r"going concern",
    ],
}


@dataclass(frozen=True)
class FilingRiskAssessment:
    risk_cleared: bool
    matched_categories: tuple[str, ...]
    matched_filings: tuple[dict, ...]
    lookback_days: int

    def to_dict(self) -> dict:
        return asdict(self)


class FilingRiskFilter:
    def __init__(self, lookback_days: int = 14):
        self.lookback_days = int(lookback_days)

    @staticmethod
    def _filing_date(row) -> pd.Timestamp | None:
        value = row.get("filing_date") or row.get("rcept_dt") or row.get("date")
        if not value:
            return None
        ts = pd.to_datetime(str(value), errors="coerce")
        return None if pd.isna(ts) else pd.Timestamp(ts).normalize()

    @staticmethod
    def _text(row: dict) -> str:
        return " ".join(str(row.get(k, "")) for k in (
            "title", "report_nm", "description", "form", "summary", "document"
        ))

    def assess(self, filings, *, as_of=None) -> FilingRiskAssessment:
        as_of_ts = pd.Timestamp(as_of or date.today()).normalize()
        cutoff = as_of_ts - pd.Timedelta(days=self.lookback_days)
        categories = set()
        hits = []
        for raw in filings or []:
            row = dict(raw)
            dt = self._filing_date(row)
            if dt is None or dt < cutoff or dt > as_of_ts:
                continue
            text = self._text(row)
            row_categories = [
                category
                for category, patterns in RISK_PATTERNS.items()
                if any(re.search(pattern, text, flags=re.I) for pattern in patterns)
            ]
            if row_categories:
                categories.update(row_categories)
                hits.append({**row, "matched_categories": row_categories})
        return FilingRiskAssessment(
            risk_cleared=not categories,
            matched_categories=tuple(sorted(categories)),
            matched_filings=tuple(hits),
            lookback_days=self.lookback_days,
        )


@dataclass(frozen=True)
class FilingFetchResult:
    available: bool
    filings: tuple[dict, ...]
    source: str
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SecEdgarClient:
    """SEC submissions client with ticker->CIK discovery.

    SEC requires a descriptive User-Agent. If SEC_USER_AGENT is not configured
    the client reports unavailable instead of sending an anonymous request.
    """
    TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(self, user_agent: str | None = None, timeout: int = 15, session=None):
        import os
        import requests

        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        self.timeout = int(timeout)
        self.session = session or requests.Session()
        self._ticker_to_cik: dict[str, str] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.user_agent)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        response = self.session.get(
            self.TICKERS_URL, headers=self._headers(), timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        mapping: dict[str, str] = {}
        rows = payload.values() if isinstance(payload, dict) else payload
        for row in rows or []:
            ticker = str((row or {}).get("ticker", "")).upper().strip()
            cik = (row or {}).get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = str(cik).zfill(10)
        self._ticker_to_cik = mapping
        return mapping

    def fetch_recent(self, symbol: str, *, as_of=None, days: int = 14) -> FilingFetchResult:
        if not self.configured:
            return FilingFetchResult(False, tuple(), "sec_edgar", "SEC_USER_AGENT not configured")
        try:
            cik = self._load_ticker_map().get(str(symbol).upper())
            if not cik:
                return FilingFetchResult(False, tuple(), "sec_edgar", "ticker CIK not found")
            response = self.session.get(
                self.SUBMISSIONS_URL.format(cik=cik),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            recent = ((response.json().get("filings") or {}).get("recent") or {})
            dates = recent.get("filingDate") or []
            end = pd.Timestamp(as_of or date.today()).normalize()
            cutoff = end - pd.Timedelta(days=int(days))
            out = []
            for i, raw_date in enumerate(dates):
                dt = pd.to_datetime(raw_date, errors="coerce")
                if pd.isna(dt) or not (cutoff <= dt <= end):
                    continue
                def _at(key):
                    values = recent.get(key) or []
                    return values[i] if i < len(values) else ""
                out.append({
                    "filing_date": str(pd.Timestamp(dt).date()),
                    "form": _at("form"),
                    "title": _at("primaryDocDescription"),
                    "document": _at("primaryDocument"),
                    "accession_number": _at("accessionNumber"),
                })
            return FilingFetchResult(True, tuple(out), "sec_edgar", None)
        except Exception as exc:
            return FilingFetchResult(False, tuple(), "sec_edgar", type(exc).__name__)


class OpenDartClient:
    """OpenDART recent-filing client with cached stock-code -> corp-code map."""

    CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
    LIST_URL = "https://opendart.fss.or.kr/api/list.json"

    def __init__(self, api_key: str | None = None, timeout: int = 15, session=None):
        import os
        import requests

        self.api_key = (api_key or os.getenv("DART_API_KEY", "")).strip()
        self.timeout = int(timeout)
        self.session = session or requests.Session()
        self._stock_to_corp: dict[str, str] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _load_corp_map(self) -> dict[str, str]:
        if self._stock_to_corp is not None:
            return self._stock_to_corp
        import io
        import zipfile
        import xml.etree.ElementTree as ET

        response = self.session.get(
            self.CORP_CODE_URL,
            params={"crtfc_key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
            if not xml_name:
                raise RuntimeError("OpenDART corpCode archive has no XML")
            root = ET.fromstring(zf.read(xml_name))
        mapping = {}
        for node in root.findall(".//list"):
            stock_code = (node.findtext("stock_code") or "").strip()
            corp_code = (node.findtext("corp_code") or "").strip()
            if stock_code and corp_code:
                mapping[stock_code.zfill(6)] = corp_code
        self._stock_to_corp = mapping
        return mapping

    def fetch_recent(self, symbol: str, *, as_of=None, days: int = 14) -> FilingFetchResult:
        if not self.configured:
            return FilingFetchResult(False, tuple(), "opendart", "DART_API_KEY not configured")
        try:
            corp_code = self._load_corp_map().get(str(symbol).zfill(6))
            if not corp_code:
                return FilingFetchResult(False, tuple(), "opendart", "stock corp_code not found")
            end = pd.Timestamp(as_of or date.today()).normalize()
            begin = end - pd.Timedelta(days=int(days))
            response = self.session.get(
                self.LIST_URL,
                params={
                    "crtfc_key": self.api_key,
                    "corp_code": corp_code,
                    "bgn_de": begin.strftime("%Y%m%d"),
                    "end_de": end.strftime("%Y%m%d"),
                    "page_count": 100,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            status = str(payload.get("status", "000"))
            # 013 = no data; that is still a successful external check.
            if status == "013":
                return FilingFetchResult(True, tuple(), "opendart", None)
            if status not in {"000", "0", "00"}:
                raise RuntimeError(f"OpenDART status={status}")
            rows = []
            for row in payload.get("list") or []:
                rows.append({
                    "filing_date": row.get("rcept_dt"),
                    "title": row.get("report_nm"),
                    "report_nm": row.get("report_nm"),
                    "receipt_no": row.get("rcept_no"),
                    "corp_name": row.get("corp_name"),
                })
            return FilingFetchResult(True, tuple(rows), "opendart", None)
        except Exception as exc:
            return FilingFetchResult(False, tuple(), "opendart", type(exc).__name__)


class FilingRiskService:
    """Market-aware filing source used by the production institutional overlay."""

    def __init__(self, *, sec_client=None, dart_client=None):
        self.sec = sec_client or SecEdgarClient()
        self.dart = dart_client or OpenDartClient()

    def fetch(self, market: str, symbol: str, *, as_of=None, days: int = 14) -> FilingFetchResult:
        if market == "us":
            return self.sec.fetch_recent(symbol, as_of=as_of, days=days)
        if market == "korea":
            return self.dart.fetch_recent(symbol, as_of=as_of, days=days)
        return FilingFetchResult(False, tuple(), "unsupported", "unsupported market")
