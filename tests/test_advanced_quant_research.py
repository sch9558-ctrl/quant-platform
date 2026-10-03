import numpy as np
import pandas as pd
from quant.hrp_allocator import hrp_allocate
from quant.residual_alpha import extract_residual_alpha,top_residual_alpha_universe
from quant.analytics.attribution import brinson_fachler
from quant.analytics.regime_detector import detect_hurst_regime

def test_hrp_weights_sum_and_positive():
    rng=np.random.default_rng(7);x=pd.DataFrame(rng.normal(0,.01,(120,4)),columns=list("ABCD"));out=hrp_allocate(x)
    assert abs(out.weights.sum()-1)<1e-10 and (out.weights>=0).all() and len(out.ordered_assets)==4

def test_residual_alpha_recovers_beta():
    rng=np.random.default_rng(4);n=180;f=pd.DataFrame({"MKT":rng.normal(0,.01,n),"SMB":rng.normal(0,.006,n),"HML":rng.normal(0,.006,n)})
    asset=.0005+1.2*f["MKT"]+.3*f["SMB"]-.2*f["HML"]+rng.normal(0,.002,n);out=extract_residual_alpha(asset,f)
    assert abs(out.betas["MKT"]-1.2)<.1 and abs(out.alpha_daily-.0005)<.001 and top_residual_alpha_universe({"A":out},.9)==["A"]

def test_brinson_components_reconcile_active_return():
    out=brinson_fachler({"tech":.6,"fin":.4},{"tech":.5,"fin":.5},{"tech":.12,"fin":.03},{"tech":.08,"fin":.04})
    assert abs(out.allocation+out.selection+out.interaction-out.active_return)<1e-12

def test_hurst_regime_returns_valid_class():
    rng=np.random.default_rng(1);p=100*np.exp(np.cumsum(rng.normal(.0005,.01,300)));out=detect_hurst_regime(pd.Series(p))
    assert 0<=out.hurst<=1 and out.regime in {"MOMENTUM","MEAN_REVERSION","NOISE"}
