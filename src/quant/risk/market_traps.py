"""Market-specific event and leverage traps for KRX/US entries."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import pandas as pd

@dataclass(frozen=True)
class MarketTrapAssessment:
    risk_cleared: bool
    reasons: tuple[str,...]
    def to_dict(self): return asdict(self)

class MarketTrapDetector:
    def __init__(self, earnings_blackout_days=3, max_credit_balance_pct=5.0, max_gap_down_pct=-3.5):
        self.earnings_blackout_days=int(earnings_blackout_days); self.max_credit_balance_pct=float(max_credit_balance_pct); self.max_gap_down_pct=float(max_gap_down_pct)

    def assess(self, *, as_of, earnings_date=None, credit_balance_pct=None, open_price=None, previous_close=None):
        reasons=[]; now=pd.Timestamp(as_of).normalize()
        if earnings_date is not None:
            event=pd.Timestamp(earnings_date).normalize(); delta=int((event-now).days)
            if 0<=delta<=self.earnings_blackout_days: reasons.append(f"EARNINGS_BLACKOUT_D-{delta}")
        if credit_balance_pct is not None and float(credit_balance_pct)>=self.max_credit_balance_pct: reasons.append("HIGH_KRX_CREDIT_BALANCE")
        if open_price is not None and previous_close not in (None,0):
            gap=(float(open_price)/float(previous_close)-1)*100
            if gap<=self.max_gap_down_pct: reasons.append("GAP_DOWN_HOLD")
        return MarketTrapAssessment(not reasons,tuple(reasons))


@dataclass(frozen=True)
class MarketTrapDataResult:
    available: bool
    source: str
    earnings_date: str | None = None
    credit_balance_pct: float | None = None
    error: str | None = None

    def to_dict(self):
        return asdict(self)


class MarketTrapDataService:
    """Fetch external event/leverage inputs required by MarketTrapDetector."""

    NAVER_ITEM_URL = "https://finance.naver.com/item/main.naver"

    def __init__(self, *, session=None, timeout: int = 15):
        import requests
        self.session = session or requests.Session()
        self.timeout = int(timeout)

    def fetch_us_earnings(self, symbol: str, *, as_of) -> MarketTrapDataResult:
        try:
            import yfinance as yf
            frame = yf.Ticker(str(symbol)).get_earnings_dates(limit=12)
            if frame is None or frame.empty:
                return MarketTrapDataResult(
                    False, "Yahoo Finance earnings calendar",
                    error="no earnings dates returned",
                )
            idx = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce", utc=True))
            idx = idx[~idx.isna()]
            if len(idx) == 0:
                return MarketTrapDataResult(
                    False, "Yahoo Finance earnings calendar",
                    error="earnings dates were not parseable",
                )
            dates = idx.tz_convert("America/New_York").tz_localize(None).normalize()
            cutoff = pd.Timestamp(as_of).normalize()
            future = dates[dates >= cutoff]
            if len(future) == 0:
                return MarketTrapDataResult(
                    False, "Yahoo Finance earnings calendar",
                    error="no future earnings date available",
                )
            return MarketTrapDataResult(
                True,
                "Yahoo Finance earnings calendar",
                earnings_date=str(future.min().date()),
            )
        except Exception as exc:
            return MarketTrapDataResult(
                False, "Yahoo Finance earnings calendar",
                error=type(exc).__name__,
            )

    def fetch_kr_credit_ratio(self, symbol: str, *, as_of=None) -> MarketTrapDataResult:
        import re
        try:
            response = self.session.get(
                self.NAVER_ITEM_URL,
                params={"code": str(symbol).zfill(6)},
                headers={"User-Agent": "Mozilla/5.0 quant-platform research"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            if response.encoding is None or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "euc-kr"
            text = response.text
            from bs4 import BeautifulSoup
            plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
            match = re.search(r"신용비율\s*([0-9]+(?:\.[0-9]+)?)\s*%", plain)
            if match is None:
                return MarketTrapDataResult(
                    False, "Naver Finance credit ratio",
                    error="credit ratio not found",
                )
            ratio = float(match.group(1))
            return MarketTrapDataResult(
                True,
                "Naver Finance credit ratio",
                credit_balance_pct=ratio,
            )
        except Exception as exc:
            return MarketTrapDataResult(
                False, "Naver Finance credit ratio",
                error=type(exc).__name__,
            )

    def fetch(self, market: str, symbol: str, *, as_of) -> MarketTrapDataResult:
        if market == "us":
            return self.fetch_us_earnings(symbol, as_of=as_of)
        if market == "korea":
            return self.fetch_kr_credit_ratio(symbol, as_of=as_of)
        return MarketTrapDataResult(False, "unsupported", error="unsupported market")
