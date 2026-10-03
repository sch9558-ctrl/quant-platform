import pytest
from quant.execution.broker_gateway import BrokerGateway

def test_mock_gateway_requires_human_approval():
    g=BrokerGateway("kis",mock_mode=True)
    denied=g.submit_limit("005930","BUY",10,70000,approved=False)
    ok=g.submit_limit("005930","BUY",10,70000,approved=True)
    assert not denied.accepted
    assert ok.accepted and ok.mode=="MOCK"
    assert g.quantity_for_weight(10_000_000,0.08,70_000)==11

def test_live_mode_stays_disabled(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING","false")
    with pytest.raises(RuntimeError):
        BrokerGateway("alpaca",mock_mode=False)
