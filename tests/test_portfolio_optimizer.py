import numpy as np
import pandas as pd
from quant.portfolio_optimizer import BlackLittermanOptimizer

def test_black_litterman_posterior_and_caps():
    names=[f"S{i}" for i in range(12)]
    cov=pd.DataFrame(np.eye(12)*0.04,index=names,columns=names)
    mw=pd.Series(1/12,index=names)
    P=np.zeros((2,12)); P[0,0]=1; P[1,1]=1
    Q=np.array([0.12,0.08])
    bl=BlackLittermanOptimizer(max_weight=0.10)
    prior=bl.implied_equilibrium_returns(cov,mw)
    mu,post=bl.posterior(cov,prior,P,Q)
    assert mu["S0"]>prior["S0"]
    assert post.shape==(12,12)
    w=bl.optimize(mu,post)
    assert (w>=-1e-9).all()
    assert w.max()<=0.100001
    assert w.sum()<=1.000001

def test_omega_decreases_with_credibility():
    o=BlackLittermanOptimizer.omega_from_credibility([0.04,0.04],[0.8,0.2])
    assert o[0,0]<o[1,1]
