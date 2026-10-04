import json
import pandas as pd
import pytest
from quant.analytics.institutional_flow import assess_krx_flow, decorrelate_candidates
from quant.notification.telegram_alert import TelegramAlert, format_trade_alert
from quant.risk.filing_filter import FilingRiskFilter
from quant.risk.market_traps import MarketTrapDetector
from quant.trading.exit_engine import ExitEngine
from quant.trading.paper_trader import PaperTrader

def test_filing_filter_blocks_recent_dilution_and_audit_warning():
    filings=[{"filing_date":"2026-10-01","title":"유상증자 결정"},{"filing_date":"2026-09-29","title":"감사의견 한정 관련 안내"},{"filing_date":"2026-08-01","title":"전환사채 발행"}]
    a=FilingRiskFilter(14).assess(filings,as_of="2026-10-04")
    assert not a.risk_cleared and "equity_dilution" in a.matched_categories and "audit_warning" in a.matched_categories
    assert "convertible_financing" not in a.matched_categories

def test_paper_trader_delegates_to_authoritative_paper_broker(tmp_path):
    from quant.broker.base import Fill
    from quant.broker.kr_paper import KoreaPaperBroker

    t=PaperTrader(
        10_000_000,
        currency="KRW",
        state_path=tmp_path/"paper_korea.json",
    )
    assert isinstance(t._broker,KoreaPaperBroker)
    buy=t.buy("005930",10,70_000,timestamp="2026-10-01")
    assert isinstance(buy,Fill)
    assert buy.price==pytest.approx(70_000)
    assert t.positions["005930"].quantity==pytest.approx(10)
    t.mark({"005930":72_000},timestamp="2026-10-02")
    sell=t.sell("005930",10,75_000,timestamp="2026-10-05")
    assert isinstance(sell,Fill)
    s=t.summary({"005930":75_000})
    assert s["closed_trades"]==1
    assert s["realized_pnl"]>0
    assert s["ledger_authority"]=="KoreaPaperBroker"
    assert t.positions=={}
    p=t.write_summary(tmp_path/"paper_trading_summary.json")
    payload=json.loads(p.read_text())
    assert payload["ledger_authority"]=="KoreaPaperBroker"
    assert payload["closed_trades"]==1


def test_paper_trader_rejects_independent_cost_overrides():
    with pytest.raises(ValueError,match="shared CostModel is authoritative"):
        PaperTrader(10_000_000,currency="KRW",commission_rate=.0002)

def test_telegram_safe_when_unconfigured():
    assert not TelegramAlert(token="",chat_id="").send_text("hello").sent
    text=format_trade_alert({"market":"korea","symbol":"005930","company":"삼성전자","action_ko":"분할 매수","entry_low":70000,"entry_high":71000,"target_1":78000,"stop_loss":68000,"risk_cleared":True})
    assert "삼성전자" in text and "Risk-Cleared" in text

def test_flow_and_decorrelation():
    flow=pd.DataFrame({"foreign":[10,12,8],"institutional":[5,4,3],"retail":[-10,-8,-4]}); assert assess_krx_flow(flow).status=="DOUBLE_BUY"
    trap=pd.DataFrame({"foreign":[-10,-12,-8],"institutional":[-5,-4,-3],"retail":[10,8,4]}); assert assess_krx_flow(trap).status=="TRAP_SUSPECTED"
    idx=pd.bdate_range("2026-01-01",periods=70); base=pd.Series(range(100,170),index=idx,dtype=float)
    out=decorrelate_candidates({"A":base,"B":base*1.01,"C":pd.Series([100+(i%5)*2+i*.1 for i in range(70)],index=idx)},{"A":.9,"B":.8,"C":.7})
    assert "A" in out.kept and "B" in out.dropped

def test_exit_engine_and_market_traps():
    from quant.risk_guard import RiskGuard

    e=ExitEngine(); s1=e.update_trailing_stop(110,2); s2=e.update_trailing_stop(112,3,previous_stop=s1); assert s2>=s1
    assert RiskGuard.position_exit_reason(
        current_price=101,
        trailing_stop=97,
        entry_price=100,
        sessions_held=15,
        time_stop_sessions=15,
        time_stop_low=-.015,
        time_stop_high=.020,
    )=="TIME_EXPIRED_EXIT"
    assert e.evaluate(current_price=101,entry_price=100,highest_high_since_entry=105,atr14=3,sessions_held=15).action=="TIME_EXPIRED_EXIT"
    assert e.evaluate(current_price=108,entry_price=100,highest_high_since_entry=120,atr14=4,sessions_held=8).action=="TAKE_PROFIT"
    a=MarketTrapDetector().assess(as_of="2026-10-04",earnings_date="2026-10-06",credit_balance_pct=5.2,open_price=96,previous_close=100)
    assert not a.risk_cleared and set(a.reasons)=={"EARNINGS_BLACKOUT_D-2","HIGH_KRX_CREDIT_BALANCE","GAP_DOWN_HOLD"}
