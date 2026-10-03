import numpy as np
import pytest
from quant.analytics.pairs_trading import analyze_pair
from quant.nlp.report_sentiment import analyze_report_text
from quant.nowcasting.customs_tracker import generate_customs_signals
from quant.macro.cross_asset import evaluate_macro_gate
from quant.execution.broker_gateway import BrokerGateway

def test_pairs_signal_detects_stationary_spread_extreme():
    rng=np.random.default_rng(5);x=np.cumsum(rng.normal(0,1,120))+100;noise=rng.normal(0,.3,120);y=2*x+noise;y[-1]+=3
    out=analyze_pair(x,y,lookback=90,z_threshold=2);assert out.cointegrated and out.signal=="PAIRS_MEAN_REVERSION" and abs(out.zscore)>=2

def test_report_sentiment_stealth_downgrade():
    out=analyze_report_text("불확실성이 높고 보수적 접근이 필요하며 단기 변동성과 도전적 환경이 예상됩니다.",target_raised=True)
    assert out.evasive_flag and out.stealth_downgrade and out.conviction_score<40

def test_customs_and_macro_signals():
    sig=generate_customs_signals([{"category":"cosmetics","hs_code":"3304","current_export":130,"prior_year_export":100}],{"cosmetics":["A","B"]})
    assert sig[0].flag=="EARNINGS_SURPRISE_EARLY_SIGNAL"
    gate=evaluate_macro_gate(market="korea",usdkrw_1d_pct=.9,sox_1d_pct=-1);assert gate.macro_risk_elevated and gate.position_scale==.5

def test_broker_gateway_is_mock_only():
    g=BrokerGateway("KIS",mock_mode=True);q=g.quantity_from_weight(10_000_000,.08,70_000);intent=g.create_limit_intent("005930","BUY",q,70_000)
    assert intent.status=="PENDING_HUMAN_APPROVAL" and intent.mock_mode
    with pytest.raises(RuntimeError):BrokerGateway("KIS",mock_mode=False)
