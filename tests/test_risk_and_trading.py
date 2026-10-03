import pytest
import pandas as pd
from quant.risk.filing_filter import classify_filings
from quant.risk.market_traps import risk_cleared
from quant.trading.paper_trader import PaperTrader

def test_filing_filter_blocks_recent_dilution():
    rows=[{"date":"2026-10-01","title":"전환사채(CB) 발행 결정"}]
    out=classify_filings(rows,as_of="2026-10-03")
    assert not out.risk_cleared
    assert out.matched_terms

def test_market_traps_block_earnings_credit_and_gap():
    assert not risk_cleared("2026-10-03",earnings_date="2026-10-05")
    assert not risk_cleared("2026-10-03",credit_ratio_pct=5.2)
    assert not risk_cleared("2026-10-03",open_price=95,previous_close=100)
    assert risk_cleared("2026-10-03",credit_ratio_pct=2.0,open_price=99,previous_close=100)

def test_paper_ledger_applies_slippage_and_tracks_summary():
    p=PaperTrader(initial_cash=1_000_000,slippage=0.001,fee_rate=0.0)
    buy=p.buy("005930",10,10000)
    assert buy==pytest.approx(10010)
    p.mark("2026-10-01",{"005930":10500})
    sell=p.sell("005930",10,11000)
    assert sell==pytest.approx(10989)
    p.mark("2026-10-02",{})
    s=p.summary()
    assert s["n_closed_trades"]==1
    assert s["win_rate"]==1.0
