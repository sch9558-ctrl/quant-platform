import numpy as np
import pandas as pd
import pytest
from quant.hrp_allocator import HRPAllocator

def test_hrp_weights_are_normalized_and_positive():
    rng=np.random.default_rng(7)
    f=rng.normal(0,0.01,200)
    df=pd.DataFrame({"A":f+rng.normal(0,0.003,200),"B":f+rng.normal(0,0.003,200),"C":rng.normal(0,0.02,200),"D":rng.normal(0,0.012,200)})
    w=HRPAllocator().allocate(df)
    assert w.sum()==pytest.approx(1.0)
    assert (w>=0).all()
    assert set(w.index)==set(df.columns)

def test_hrp_one_asset():
    assert HRPAllocator().allocate(pd.DataFrame({"A":[.01,-.01,.02]}))["A"]==pytest.approx(1.0)
