import numpy as np
import pandas as pd
from quant.signal.wavelet_filter import apply_wavelet_denoising
from quant.pipeline.institutional_overlay import evaluate_candidate

def test_wavelet_denoise_preserves_shape_and_reduces_roughness():
    rng=np.random.default_rng(3);base=np.linspace(100,120,128);x=base+rng.normal(0,2,128);out=apply_wavelet_denoising(pd.Series(x),level=2)
    assert len(out)==len(x) and out.diff().dropna().std()<pd.Series(x).diff().dropna().std()

def test_overlay_rejects_filing_risk_and_accepts_clean_high_alpha():
    c={"market":"korea","price":100,"volatility":.2,"composite_score":.9,"trade_plan":{"target_1":112}}
    bad=evaluate_candidate(c,filings=[{"filing_date":"2026-10-03","title":"유상증자 결정"}],as_of="2026-10-04",adv_notional=1e9,order_notional=1e6)
    assert not bad.approved and not bad.risk_cleared
    good=evaluate_candidate(c,filings=[],as_of="2026-10-04",adv_notional=1e9,order_notional=1e6)
    assert good.approved and good.net_alpha_pct>3


def test_overlay_fails_closed_when_filing_feed_is_unavailable():
    c={"market":"us","price":100,"volatility":.2,"composite_score":.9,"trade_plan":{"target_1":115}}
    out=evaluate_candidate(c,filings=None,as_of="2026-10-04",adv_notional=1e9,order_notional=1e6)
    assert not out.approved
    assert not out.risk_cleared
    assert not out.external_checks_complete
    assert "FILING_DATA_UNAVAILABLE" in out.reasons
