import pandas as pd
from quant.analytics.institutional_flow import classify_krx_flow,decorrelate_candidates

def test_dual_buying_and_trap():
    good=pd.DataFrame({"foreign_net":[1,2,3],"institutional_net":[2,2,1],"retail_net":[-1,-2,-3]})
    bad=pd.DataFrame({"foreign_net":[-1,-2],"institutional_net":[-2,-1],"retail_net":[3,4]})
    assert classify_krx_flow(good).status=="DUAL_BUYING"
    assert classify_krx_flow(good).tradable
    assert classify_krx_flow(bad).status=="TRAP_SUSPECTED"
    assert not classify_krx_flow(bad).tradable

def test_decorrelation_keeps_higher_score():
    r=pd.DataFrame({"A":[.01,.02,-.01,.03],"B":[.011,.021,-.009,.031],"C":[-.02,.01,.02,-.01]})
    kept=decorrelate_candidates(r,pd.Series({"A":0.9,"B":0.8,"C":0.7}),0.65)
    assert "A" in kept and "B" not in kept
