import pandas as pd

from quant.risk.market_traps import MarketTrapDataService


class _Response:
    def __init__(self,text,status=200):
        self.text=text
        self.status_code=status
        self.encoding="utf-8"
        self.apparent_encoding="utf-8"
    def raise_for_status(self):
        if self.status_code>=400:
            raise RuntimeError("http")


class _Session:
    def __init__(self,text):
        self.text=text
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return _Response(self.text)


def test_korean_credit_ratio_is_parsed_from_public_page():
    session=_Session("<html><body><span>신용비율</span> 5.25 %</body></html>")
    service=MarketTrapDataService(session=session)
    result=service.fetch_kr_credit_ratio("005930",as_of="2026-10-04")
    assert result.available is True
    assert result.credit_balance_pct==5.25
    assert session.calls[0][1]["params"]["code"]=="005930"


def test_korean_credit_ratio_missing_value_fails_closed():
    service=MarketTrapDataService(session=_Session("<html><body>신용정보 없음</body></html>"))
    result=service.fetch_kr_credit_ratio("005930",as_of="2026-10-04")
    assert result.available is False
    assert result.credit_balance_pct is None
    assert result.error=="credit ratio not found"


def test_us_earnings_selects_nearest_future_date(monkeypatch):
    class _Ticker:
        def get_earnings_dates(self,limit=12):
            idx=pd.DatetimeIndex([
                "2026-09-15 16:00:00-04:00",
                "2026-10-06 16:00:00-04:00",
                "2027-01-20 16:00:00-05:00",
            ])
            return pd.DataFrame({"EPS Estimate":[1,2,3]},index=idx)
    import yfinance as yf
    monkeypatch.setattr(yf,"Ticker",lambda symbol:_Ticker())
    result=MarketTrapDataService().fetch_us_earnings("AAPL",as_of="2026-10-04")
    assert result.available is True
    assert result.earnings_date=="2026-10-06"


def test_us_earnings_without_future_date_fails_closed(monkeypatch):
    class _Ticker:
        def get_earnings_dates(self,limit=12):
            return pd.DataFrame(
                {"EPS Estimate":[1]},
                index=pd.DatetimeIndex(["2026-09-15"]),
            )
    import yfinance as yf
    monkeypatch.setattr(yf,"Ticker",lambda symbol:_Ticker())
    result=MarketTrapDataService().fetch_us_earnings("AAPL",as_of="2026-10-04")
    assert result.available is False
    assert result.earnings_date is None
    assert result.error=="no future earnings date available"
