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
