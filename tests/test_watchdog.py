import pandas as pd
from quant.risk.watchdog import inspect_watchdog

def test_watchdog_enters_safe_mode_on_integrity_issue():
    df=pd.DataFrame({"close":[100,140],"return_1d":[0.01,0.40]})
    out=inspect_watchdog(df,{"tech":0.45},[25,120])
    assert out.safe_mode
    assert "PRICE_JUMP_GT_30PCT" in out.issues
    assert "SECTOR_WEIGHT_GT_40PCT" in out.issues
    assert "TARGET_GAP_GT_100PCT" in out.issues

def test_watchdog_clean():
    out=inspect_watchdog(pd.DataFrame({"close":[100,102],"return_1d":[.01,.02]}),{"tech":.3},[20])
    assert not out.safe_mode
