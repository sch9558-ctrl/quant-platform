import numpy as np
import pandas as pd
from quant.residual_alpha import fit_residual_alpha, top_residual_alpha

def test_residual_alpha_recovers_intercept_and_beta():
    rng=np.random.default_rng(3); n=400
    mkt=rng.normal(0,0.01,n); smb=rng.normal(0,0.006,n); eps=rng.normal(0,0.004,n)
    asset=0.0005+1.2*mkt+0.3*smb+eps
    idx=pd.bdate_range("2025-01-01",periods=n)
    factors=pd.DataFrame({"MKT":mkt,"SMB":smb},index=idx)
    result=fit_residual_alpha(pd.Series(asset,index=idx),factors,0.0)
    assert abs(result.alpha-0.0005)<0.001
    assert abs(result.betas["MKT"]-1.2)<0.1
    assert len(result.residuals)==n

def test_top_residual_alpha_selects_tail():
    rng=np.random.default_rng(1); idx=pd.bdate_range("2025-01-01",periods=260)
    f=pd.DataFrame({"MKT":rng.normal(0,.01,260)},index=idx)
    results={}
    for i,a in enumerate([0.0,.0002,.001]):
        results[str(i)]=fit_residual_alpha(pd.Series(a+f["MKT"].values+rng.normal(0,.003,260),index=idx),f)
    assert len(top_residual_alpha(results,0.67))>=1
