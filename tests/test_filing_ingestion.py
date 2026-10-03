from quant.risk.filing_filter import FilingRiskService, OpenDartClient, SecEdgarClient


class _Response:
    def __init__(self,payload,status=200):
        self._payload=payload
        self.status_code=status
        self.content=b""
    def raise_for_status(self):
        if self.status_code>=400:
            raise RuntimeError("http")
    def json(self):
        return self._payload


class _Session:
    def __init__(self,responses):
        self.responses=list(responses)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return self.responses.pop(0)


def test_sec_edgar_resolves_cik_and_filters_recent_filings():
    session=_Session([
        _Response({"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}}),
        _Response({"filings":{"recent":{
            "filingDate":["2026-10-02","2026-08-01"],
            "form":["8-K","10-Q"],
            "primaryDocument":["a8k.htm","a10q.htm"],
            "primaryDocDescription":["Current report","Quarterly report"],
            "accessionNumber":["1","2"],
        }}}),
    ])
    client=SecEdgarClient(user_agent="quant-platform test contact@example.com",session=session)
    result=client.fetch_recent("AAPL",as_of="2026-10-04",days=14)
    assert result.available is True
    assert result.source=="sec_edgar"
    assert len(result.filings)==1
    assert result.filings[0]["form"]=="8-K"
    assert "CIK0000320193.json" in session.calls[1][0]


def test_filing_clients_fail_closed_when_credentials_are_missing():
    sec=SecEdgarClient(user_agent="")
    dart=OpenDartClient(api_key="")
    assert sec.fetch_recent("AAPL",as_of="2026-10-04").available is False
    assert dart.fetch_recent("005930",as_of="2026-10-04").available is False


class _Client:
    def __init__(self,source):
        self.source=source
    def fetch_recent(self,symbol,**kwargs):
        from quant.risk.filing_filter import FilingFetchResult
        return FilingFetchResult(True,tuple(),self.source,None)


def test_filing_service_dispatches_by_market():
    service=FilingRiskService(sec_client=_Client("sec"),dart_client=_Client("dart"))
    assert service.fetch("us","AAPL").source=="sec"
    assert service.fetch("korea","005930").source=="dart"
    assert service.fetch("other","X").available is False
