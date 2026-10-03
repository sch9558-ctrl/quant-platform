import numpy as np
import pandas as pd
from quant.nlp.report_sentiment import analyze_report
from quant.nowcasting.customs_tracker import detect_surprise_signals
from quant.signal.wavelet_filter import apply_wavelet_denoising
from quant.tax_optimizer import tax_loss_harvest

def test_sentiment_customs_wavelet_and_tax():
    s=analyze_report("불확실성 리스크 도전적 단기 변동성",target_raised=True)
    assert s.evasive_flag and s.stealth_downgrade
    rows=pd.DataFrame([{"category":"cosmetics","current_export":130,"prior_export":100}])
    sig=detect_surprise_signals(rows,{"cosmetics":["AAA"]})
    assert sig and sig[0].signal=="EARNINGS_SURPRISE_EARLY_SIGNAL"
    x=pd.Series(np.sin(np.linspace(0,6.28,128))+np.random.default_rng(1).normal(0,.2,128))
    y=apply_wavelet_denoising(x)
    assert len(y)==len(x)
    rec=tax_loss_harvest(4_000_000,[{"symbol":"X","unrealized_pnl_krw":-1_000_000},{"symbol":"Y","unrealized_pnl_krw":-800_000}])
    assert rec and sum(r.suggested_realization_krw for r in rec)<=1_500_000
