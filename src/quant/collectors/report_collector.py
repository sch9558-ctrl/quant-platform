"""Metadata-only analyst report collectors.

Only report metadata needed for quantitative validation is retained. Report
body/PDF content is not archived. This keeps the system focused on dates,
ratings and targets while avoiding redistribution of publisher content.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import os
import re
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup


@dataclass
class AnalystReport:
    market: str
    symbol: str
    company: str | None
    published_at: str
    institution: str
    analyst: str | None
    target_price: float | None
    rating: str
    currency: str
    source: str
    source_url: str | None = None
    previous_rating: str | None = None
    previous_target_price: float | None = None
    action: str | None = None
    is_consensus: bool = False

    def to_dict(self):
        return asdict(self)

    def dedupe_key(self) -> tuple:
        # Consensus snapshots and individual actions are intentionally
        # separate records even when they share the same date.
        return (
            self.source,
            self.market,
            self.symbol,
            self.published_at,
            self.institution,
            self.analyst or "",
            self.rating,
            self.target_price,
            bool(self.is_consensus),
        )


def dedupe_reports(reports: Iterable[AnalystReport]) -> list[AnalystReport]:
    seen = set()
    out = []
    for report in reports:
        key = report.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        out.append(report)
    return out


def normalize_rating(value) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    if any(k in text for k in (
        "strongbuy", "buy", "매수", "outperform", "overweight",
        "accumulate", "positive",
    )):
        return "BUY"
    if any(k in text for k in (
        "sell", "매도", "underperform", "underweight", "negative", "reduce",
    )):
        return "SELL"
    if any(k in text for k in (
        "hold", "neutral", "보유", "중립", "marketperform", "equalweight",
    )):
        return "HOLD"
    return "UNKNOWN"


def _number(text):
    if text is None:
        return None
    match = re.search(r"(-?\d[\d,]*(?:\.\d+)?)", str(text))
    return float(match.group(1).replace(",", "")) if match else None


class NaverResearchCollector:
    LIST_URL = "https://finance.naver.com/research/company_list.naver"

    def __init__(self, timeout=15, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 quant-platform/1.0 personal-research",
        )

    @staticmethod
    def parse_detail(html):
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        target_match = re.search(r"목표가\s*[:|]?\s*([\d,]+)", text)
        rating_match = re.search(
            r"투자의견\s*[:|]?\s*([A-Za-z가-힣 /+-]+?)(?=\s{2,}|목표가|작성일|$)",
            text,
        )
        return (
            _number(target_match.group(1)) if target_match else None,
            normalize_rating(rating_match.group(1) if rating_match else ""),
        )

    @staticmethod
    def parse_list(html):
        """Parse the public Naver company-report table.

        Current columns are: 종목명, 제목, 증권사, 첨부, 작성일, 조회수.
        We select links semantically rather than relying on a brittle fixed
        column index.
        """
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for row in soup.select("tr"):
            detail = row.find("a", href=re.compile(r"company_read\.naver"))
            item = row.find("a", href=re.compile(r"/item/main\.naver\?code=\d{6}"))
            if not detail or not item:
                continue

            symbol_match = re.search(r"code=(\d{6})", item.get("href", ""))
            if not symbol_match:
                continue

            cells = row.find_all("td")
            cell_text = [c.get_text(" ", strip=True) for c in cells]
            # The institution is the first plain-text cell after the report
            # title. On the current Naver table that is column 3.
            institution = cell_text[2] if len(cell_text) >= 3 else "미상"
            date_text = next(
                (
                    value
                    for value in cell_text
                    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}|\d{4}[.-]\d{2}[.-]\d{2}", value)
                ),
                None,
            )
            if date_text:
                published = date_text.replace(".", "-")
                if len(published.split("-")[0]) == 2:
                    published = "20" + published
            else:
                published = None

            out.append(
                {
                    "symbol": symbol_match.group(1),
                    "company": item.get_text(" ", strip=True),
                    "institution": institution,
                    "analyst": None,
                    "published_at": published,
                    "detail_url": requests.compat.urljoin(
                        "https://finance.naver.com", detail.get("href", "")
                    ),
                }
            )
        return out

    def collect(self, symbols: Iterable[str] | None = None, max_pages=3):
        wanted = {str(s).zfill(6) for s in symbols} if symbols else None
        out = []
        for page in range(1, max_pages + 1):
            response = self.session.get(
                self.LIST_URL, params={"page": page}, timeout=self.timeout
            )
            response.raise_for_status()
            rows = self.parse_list(response.text)
            if not rows:
                break
            for row in rows:
                if (
                    not row["published_at"]
                    or (wanted is not None and row["symbol"] not in wanted)
                ):
                    continue
                try:
                    detail = self.session.get(row["detail_url"], timeout=self.timeout)
                    detail.raise_for_status()
                    target, rating = self.parse_detail(detail.text)
                except Exception:
                    target, rating = None, "UNKNOWN"
                out.append(
                    AnalystReport(
                        "korea",
                        row["symbol"],
                        row["company"],
                        row["published_at"],
                        row["institution"],
                        row["analyst"],
                        target,
                        rating,
                        "KRW",
                        "naver_finance",
                        row["detail_url"],
                    )
                )
        return dedupe_reports(out)


class YahooAnalystCollector:
    """Yahoo analyst actions plus the latest aggregate target snapshot."""

    def collect(self, symbols):
        import yfinance as yf

        out = []
        today = str(pd.Timestamp.now(tz="UTC").date())
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            try:
                upgrades = ticker.get_upgrades_downgrades()
                if upgrades is not None and not upgrades.empty:
                    for idx, row in upgrades.head(200).iterrows():
                        target = _number(
                            row.get("currentPriceTarget")
                            if "currentPriceTarget" in row.index
                            else None
                        )
                        prior_target = _number(
                            row.get("priorPriceTarget")
                            if "priorPriceTarget" in row.index
                            else None
                        )
                        out.append(
                            AnalystReport(
                                "us",
                                symbol,
                                None,
                                str(pd.Timestamp(idx).date()),
                                str(row.get("Firm") or row.get("firm") or "Unknown"),
                                None,
                                target,
                                normalize_rating(row.get("ToGrade") or row.get("toGrade")),
                                "USD",
                                "yahoo_finance",
                                f"https://finance.yahoo.com/quote/{symbol}/analysis/",
                                normalize_rating(row.get("FromGrade") or row.get("fromGrade")),
                                prior_target,
                                str(row.get("Action") or row.get("action") or "") or None,
                                False,
                            )
                        )
            except Exception:
                pass

            try:
                targets = ticker.get_analyst_price_targets()
                if isinstance(targets, dict):
                    target = (
                        targets.get("mean")
                        or targets.get("meanPrice")
                        or targets.get("targetMeanPrice")
                    )
                    if target:
                        out.append(
                            AnalystReport(
                                "us",
                                symbol,
                                None,
                                today,
                                "Yahoo Finance Consensus",
                                None,
                                float(target),
                                "UNKNOWN",
                                "USD",
                                "yahoo_finance_consensus",
                                f"https://finance.yahoo.com/quote/{symbol}/analysis/",
                                is_consensus=True,
                            )
                        )
            except Exception:
                pass
        return dedupe_reports(out)


class FinnhubAnalystCollector:
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, token=None, timeout=15):
        self.token = token or os.getenv("FINNHUB_API_KEY", "")
        self.timeout = timeout

    def _get(self, path, **params):
        response = requests.get(
            self.BASE + path,
            params={**params, "token": self.token},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def collect(self, symbols, start=None, end=None):
        if not self.token:
            return []
        end = end or str(date.today())
        start = start or str((pd.Timestamp(end) - pd.DateOffset(years=2)).date())
        out = []
        for symbol in symbols:
            try:
                rows = self._get(
                    "/stock/upgrade-downgrade",
                    symbol=symbol,
                    **{"from": start, "to": end},
                )
                for row in rows or []:
                    published = pd.to_datetime(
                        row.get("gradeTime"), unit="s", errors="coerce"
                    )
                    if pd.isna(published):
                        continue
                    out.append(
                        AnalystReport(
                            "us",
                            symbol,
                            None,
                            str(published.date()),
                            str(row.get("company") or "Unknown"),
                            None,
                            _number(row.get("currentPriceTarget")),
                            normalize_rating(row.get("toGrade")),
                            "USD",
                            "finnhub",
                            None,
                            normalize_rating(row.get("fromGrade")),
                            _number(row.get("priorPriceTarget")),
                            str(row.get("action") or "") or None,
                        )
                    )
            except Exception:
                pass

            # Finnhub exposes a current aggregate price-target endpoint. This
            # is consensus metadata, not an individual bank call, so it is
            # deliberately labelled as consensus and never attributed to an IB.
            try:
                target_row = self._get("/stock/price-target", symbol=symbol) or {}
                target = _number(
                    target_row.get("targetMean") or target_row.get("target_mean")
                )
                updated = (
                    target_row.get("lastUpdated")
                    or target_row.get("last_updated")
                    or end
                )
                if target:
                    out.append(
                        AnalystReport(
                            "us",
                            symbol,
                            None,
                            str(pd.Timestamp(updated).date()),
                            "Finnhub Consensus",
                            None,
                            target,
                            "UNKNOWN",
                            "USD",
                            "finnhub_consensus",
                            None,
                            is_consensus=True,
                        )
                    )
            except Exception:
                pass
        return dedupe_reports(out)


class CSVReportCollector:
    """Licensed/user-owned archive adapter.

    Expected columns are intentionally simple so exports from a broker,
    Bloomberg/FactSet/Refinitiv entitlement, or a hand-maintained archive can
    be normalized without committing proprietary report bodies.
    """

    def collect_file(self, path):
        df = pd.read_csv(path, dtype={"symbol": str})
        required = {
            "market",
            "symbol",
            "published_at",
            "institution",
            "rating",
            "currency",
            "source",
        }
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"missing report columns: {sorted(missing)}")
        out = []
        for _, row in df.iterrows():
            symbol = str(row["symbol"])
            if str(row["market"]).lower() == "korea":
                symbol = symbol.zfill(6)
            out.append(
                AnalystReport(
                    str(row["market"]).lower(),
                    symbol,
                    None if pd.isna(row.get("company")) else str(row.get("company")),
                    str(pd.Timestamp(row["published_at"]).date()),
                    str(row["institution"]),
                    None if pd.isna(row.get("analyst")) else str(row.get("analyst")),
                    None if pd.isna(row.get("target_price")) else float(row.get("target_price")),
                    normalize_rating(row.get("rating")),
                    str(row["currency"]),
                    str(row["source"]),
                    None if pd.isna(row.get("source_url")) else str(row.get("source_url")),
                    None if pd.isna(row.get("previous_rating")) else normalize_rating(row.get("previous_rating")),
                    None if pd.isna(row.get("previous_target_price")) else float(row.get("previous_target_price")),
                    None if pd.isna(row.get("action")) else str(row.get("action")),
                    bool(row.get("is_consensus", False)),
                )
            )
        return dedupe_reports(out)
