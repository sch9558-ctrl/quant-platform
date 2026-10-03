import pandas as pd
from quant.analytics.attribution import brinson_fachler
from quant.trading.execution_scheduler import build_execution_schedule

def test_brinson_sums_and_execution_schedule_quantity():
    idx=["tech","health"]
    out=brinson_fachler(pd.Series([.6,.4],index=idx),pd.Series([.5,.5],index=idx),pd.Series([.1,.03],index=idx),pd.Series([.08,.04],index=idx))
    assert {"allocation","selection","interaction","active_contribution"}.issubset(out.columns)
    slices=build_execution_schedule(11,71500,72800)
    assert sum(x.quantity for x in slices)==11
    assert len(slices)==4
