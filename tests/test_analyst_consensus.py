import pandas as pd
from quant.analytics.analyst_consensus import AnalystTracker
from quant.collectors.report_collector import AnalystReport, normalize_rating

def prices():
    idx=pd.bdate_range("2026-01-02",periods=90); close=pd.Series([100+i*.5 for i in range(90)],index=idx)
    return pd.DataFrame({"open":close,"high":close+2,"low":close-2,"close":close,"volume":1000},index=idx)

def test_target_hit_and_credibility():
    r=AnalystReport("us","ABC","ABC","2026-01-02","Bank A","Analyst",110,"BUY","USD","fixture")
    rows=AnalystTracker().evaluate_report(r,prices()); m3=next(x for x in rows if x.horizon=="3m")
    assert m3.hit is True and m3.sessions_to_hit is not None
    score=AnalystTracker.credibility(rows)
    assert 0<=score["credibility_score"]<=100 and score["tier"] in {"S","A","B","C"}

def test_rating_normalization():
    assert normalize_rating("Strong Buy")=="BUY"
    assert normalize_rating("중립")=="HOLD"
    assert normalize_rating("Underweight")=="SELL"
