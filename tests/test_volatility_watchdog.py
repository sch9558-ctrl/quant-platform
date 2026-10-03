import pandas as pd
from quant.volatility_targeting import VolatilityTargeting
from quant.analytics.consensus_acceleration import measure_consensus_acceleration
from quant.trading.execution_scheduler import build_execution_schedule
from quant.risk.watchdog import QuantWatchdog

def test_vol_target_scales_down_high_vol():
    r=pd.Series([.03,-.025,.035,-.03,.028,-.026]*8)
    out=VolatilityTargeting(target_vol=.12).target(r)
    assert out.realized_vol>.12
    assert 0<out.risky_weight<1
    assert abs(out.risky_weight+out.cash_weight-1)<1e-12

def test_consensus_acceleration_positive():
    idx=pd.date_range("2026-08-01",periods=40)
    vals=pd.Series([100+i*.1 for i in range(33)]+[104,105,106,108,111,115,120],index=idx)
    out=measure_consensus_acceleration(vals)
    assert out.velocity_30d>0 and out.acceleration>0
    assert out.label=="CONSENSUS_ACCELERATING"

def test_execution_schedule_sums_exact_quantity():
    rows=build_execution_schedule(11,100)
    assert sum(x.quantity for x in rows)==11
    assert [x.time for x in rows]==["09:40","10:30","13:30","14:50"]

def test_watchdog_enters_safe_mode_and_discards_bad_report():
    prices={"A":pd.Series([100,101,150])}
    out=QuantWatchdog().inspect(price_map=prices,sector_weights={"tech":.45},reports=[{"target_price":250,"current_price":100}])
    assert out.safe_mode
    assert 0 in out.discarded_report_indices
    assert any(x.startswith("PRICE_JUMP") for x in out.issues)
