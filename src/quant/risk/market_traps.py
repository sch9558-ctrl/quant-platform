"""Market-specific event and leverage traps for KRX/US entries."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import os
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

    KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
    KIS_TOKEN_URL = KIS_BASE_URL + "/oauth2/tokenP"
    KIS_CREDIT_URL = KIS_BASE_URL + "/uapi/domestic-stock/v1/quotations/daily-credit-balance"

    def __init__(
        self,
        *,
        session=None,
        timeout: int = 15,
        kis_app_key: str | None = None,
        kis_app_secret: str | None = None,
    ):
        import requests
        self.session = session or requests.Session()
        self.timeout = int(timeout)
        self.kis_app_key = (kis_app_key or os.getenv("KIS_APP_KEY", "")).strip()
        self.kis_app_secret = (kis_app_secret or os.getenv("KIS_APP_SECRET", "")).strip()
        self._kis_access_token: str | None = None

    @property
    def kis_configured(self) -> bool:
        return bool(self.kis_app_key and self.kis_app_secret)

    def _kis_token(self) -> str:
        if self._kis_access_token:
            return self._kis_access_token
        if not self.kis_configured:
            raise RuntimeError("KIS credentials not configured")
        response = self.session.post(
            self.KIS_TOKEN_URL,
            headers={"content-type": "application/json"},
            data=json.dumps({
                "grant_type": "client_credentials",
                "appkey": self.kis_app_key,
                "appsecret": self.kis_app_secret,
            }),
            timeout=self.timeout,
        )
        response.raise_for_status()
        token = str((response.json() or {}).get("access_token") or "").strip()
        if not token:
            raise RuntimeError("KIS token response missing access_token")
        self._kis_access_token = token
        return token

    def fetch_us_earnings(self, symbol: str, *, as_of) -> MarketTrapDataResult:
        try:
            import yfinance as yf
            frame = yf.Ticker(str(symbol)).get_earnings_dates(limit=12)
            if frame is None or frame.empty:
                return MarketTrapDataResult(
                    False, "Yahoo Finance earnings calendar",
                    error="no earnings dates returned",
                )
            normalized_dates = []
            for raw in frame.index:
                try:
                    ts = pd.Timestamp(raw)
                    if ts.tzinfo is None:
                        ts = ts.tz_localize("America/New_York")
                    else:
                        ts = ts.tz_convert("America/New_York")
                    normalized_dates.append(ts.tz_localize(None).normalize())
                except Exception:
                    continue
            if not normalized_dates:
                return MarketTrapDataResult(
                    False, "Yahoo Finance earnings calendar",
                    error="earnings dates were not parseable",
                )
            dates = pd.DatetimeIndex(normalized_dates)
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
        """Fetch per-symbol credit-balance ratio from KIS Open API.

        This is a read-only quotations endpoint. Missing credentials or any
        response-contract problem returns unavailable; callers fail closed.
        """
        if not self.kis_configured:
            return MarketTrapDataResult(
                False,
                "KIS Open API daily credit balance",
                error="KIS_APP_KEY/KIS_APP_SECRET not configured",
            )
        try:
            token = self._kis_token()
            date_str = pd.Timestamp(as_of or pd.Timestamp.today()).strftime("%Y%m%d")
            response = self.session.get(
                self.KIS_CREDIT_URL,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {token}",
                    "appkey": self.kis_app_key,
                    "appsecret": self.kis_app_secret,
                    "tr_id": "FHPST04760000",
                },
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_COND_SCR_DIV_CODE": "20476",
                    "FID_INPUT_ISCD": str(symbol).zfill(6),
                    "FID_INPUT_DATE_1": date_str,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json() or {}
            if str(payload.get("rt_cd", "")) != "0":
                raise RuntimeError("KIS credit-balance API returned non-success")
            rows = payload.get("output") or []
            if not rows:
                return MarketTrapDataResult(
                    False,
                    "KIS Open API daily credit balance",
                    error="credit-balance output empty",
                )
            raw = rows[0].get("whol_loan_rmnd_rate")
            if raw in (None, ""):
                return MarketTrapDataResult(
                    False,
                    "KIS Open API daily credit balance",
                    error="whol_loan_rmnd_rate missing",
                )
            ratio = float(str(raw).replace(",", ""))
            if not 0.0 <= ratio <= 100.0:
                raise ValueError("credit ratio outside 0..100")
            return MarketTrapDataResult(
                True,
                "KIS Open API daily credit balance",
                credit_balance_pct=ratio,
            )
        except Exception as exc:
            return MarketTrapDataResult(
                False,
                "KIS Open API daily credit balance",
                error=type(exc).__name__,
            )

    def fetch(self, market: str, symbol: str, *, as_of) -> MarketTrapDataResult:
        if market == "us":
            return self.fetch_us_earnings(symbol, as_of=as_of)
        if market == "korea":
            return self.fetch_kr_credit_ratio(symbol, as_of=as_of)
        return MarketTrapDataResult(False, "unsupported", error="unsupported market")
