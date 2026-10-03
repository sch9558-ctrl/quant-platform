import numpy as np
import pandas as pd

from quant.portfolio_optimizer import BlackLittermanOptimizer


def test_black_litterman_posterior_moves_toward_confident_view():
    symbols=["A","B","C"]
    cov=pd.DataFrame(np.diag([0.04,0.03,0.02]),index=symbols,columns=symbols)
    opt=BlackLittermanOptimizer(max_weight=0.6)
    prior=opt.implied_equilibrium_returns(cov,{"A":0.4,"B":0.3,"C":0.3})
    post=opt.posterior(
        cov,{"A":0.4,"B":0.3,"C":0.3},
        P=[[1,0,0]],Q=[prior["A"]+0.08],confidences=[0.9],
    )
    assert post.expected_returns["A"] > prior["A"]
    assert post.omega.shape==(1,1)


def test_optimizer_respects_position_sector_and_cash_constraints():
    symbols=[f"S{i}" for i in range(12)]
    cov=pd.DataFrame(np.eye(12)*0.02,index=symbols,columns=symbols)
    mu=pd.Series(np.linspace(0.08,0.16,12),index=symbols)
    sectors={s:("tech" if i<6 else "finance") for i,s in enumerate(symbols)}
    opt=BlackLittermanOptimizer(max_weight=0.10,sector_band=0.05,risk_aversion=1.0)
    result=opt.optimize(
        mu,cov,sectors=sectors,
        benchmark_sector_weights={"tech":0.5,"finance":0.5},
    )
    assert result.success
    assert (result.weights >= -1e-10).all()
    assert (result.weights <= 0.10+1e-8).all()
    assert result.weights.sum() <= 1.0+1e-8
    assert abs(result.weights[[s for s in symbols if sectors[s]=="tech"]].sum()-0.5)<=0.05+1e-6
    assert abs(result.weights[[s for s in symbols if sectors[s]=="finance"]].sum()-0.5)<=0.05+1e-6
    assert 0 <= result.cash_weight <= 1
