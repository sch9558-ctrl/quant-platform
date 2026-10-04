import pandas as pd

from quant.risk.market_traps import MarketTrapDataService


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http")

    def json(self):
        return self._payload


class _Session:
    def __init__(self, *, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.get_responses.pop(0)


def test_korean_credit_ratio_is_parsed_from_kis_contract():
    session = _Session(
        post_responses=[_Response({"access_token": "fixture-token"})],
        get_responses=[_Response({
            "rt_cd": "0",
            "output": [{"whol_loan_rmnd_rate": "5.25"}],
        })],
    )
    service = MarketTrapDataService(
        session=session,
        kis_app_key="fixture-app-key",
        kis_app_secret="fixture-app-secret",
    )
    result = service.fetch_kr_credit_ratio("005930", as_of="2026-10-04")
    assert result.available is True
    assert result.credit_balance_pct == 5.25
    assert result.source == "KIS Open API daily credit balance"
    assert session.gets[0][1]["params"]["FID_INPUT_ISCD"] == "005930"
    assert session.gets[0][1]["params"]["FID_INPUT_DATE_1"] == "20261004"
    assert session.gets[0][1]["headers"]["tr_id"] == "FHPST04760000"
    assert session.gets[0][1]["headers"]["custtype"] == "P"
    assert session.gets[0][1]["headers"]["tr_cont"] == ""


def test_korean_credit_ratio_missing_credentials_fails_closed():
    service = MarketTrapDataService(
        session=_Session(),
        kis_app_key="",
        kis_app_secret="",
    )
    result = service.fetch_kr_credit_ratio("005930", as_of="2026-10-04")
    assert result.available is False
    assert result.credit_balance_pct is None
    assert "not configured" in result.error


def test_korean_credit_ratio_missing_field_fails_closed():
    session = _Session(
        post_responses=[_Response({"access_token": "fixture-token"})],
        get_responses=[_Response({"rt_cd": "0", "output": [{}]})],
    )
    service = MarketTrapDataService(
        session=session,
        kis_app_key="fixture-app-key",
        kis_app_secret="fixture-app-secret",
    )
    result = service.fetch_kr_credit_ratio("005930", as_of="2026-10-04")
    assert result.available is False
    assert result.credit_balance_pct is None
    assert result.error == "whol_loan_rmnd_rate missing"


def test_us_earnings_selects_nearest_future_date_across_dst(monkeypatch):
    class _Ticker:
        def get_earnings_dates(self, limit=12):
            # Object index intentionally mixes EDT (-04:00) and EST (-05:00).
            # A bulk DatetimeIndex coercion is invalid on newer pandas.
            idx = pd.Index([
                "2026-09-15 16:00:00-04:00",
                "2026-10-06 16:00:00-04:00",
                "2027-01-20 16:00:00-05:00",
            ], dtype="object")
            return pd.DataFrame({"EPS Estimate": [1, 2, 3]}, index=idx)

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", lambda symbol: _Ticker())
    result = MarketTrapDataService().fetch_us_earnings("AAPL", as_of="2026-10-04")
    assert result.available is True
    assert result.earnings_date == "2026-10-06"


def test_us_earnings_without_future_date_fails_closed(monkeypatch):
    class _Ticker:
        def get_earnings_dates(self, limit=12):
            return pd.DataFrame(
                {"EPS Estimate": [1]},
                index=pd.Index(["2026-09-15"], dtype="object"),
            )

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", lambda symbol: _Ticker())
    result = MarketTrapDataService().fetch_us_earnings("AAPL", as_of="2026-10-04")
    assert result.available is False
    assert result.earnings_date is None
    assert result.error == "no future earnings date available"


def test_korean_credit_ratio_requires_explicit_as_of():
    service = MarketTrapDataService(
        session=_Session(),
        kis_app_key="fixture-app-key",
        kis_app_secret="fixture-app-secret",
    )
    result = service.fetch_kr_credit_ratio("005930", as_of=None)
    assert result.available is False
    assert result.credit_balance_pct is None
    assert "as_of is required" in result.error
