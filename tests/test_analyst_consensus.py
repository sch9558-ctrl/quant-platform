import pandas as pd

from quant.analytics.analyst_consensus import AnalystTracker
from quant.collectors.report_collector import AnalystReport, normalize_rating


def prices(periods=90):
    idx = pd.bdate_range("2026-01-02", periods=periods)
    close = pd.Series([100 + i * .5 for i in range(periods)], index=idx)
    return pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1000},
        index=idx,
    )


def report(target=110, rating="BUY", institution="Bank A", date="2026-01-02"):
    return AnalystReport(
        "us", "ABC", "ABC", date, institution, "Analyst",
        target, rating, "USD", "fixture",
    )


def test_target_hit_and_credibility():
    rows = AnalystTracker().evaluate_report(report(), prices())
    m3 = next(x for x in rows if x.horizon == "3m")
    assert m3.hit is True
    assert m3.sessions_to_hit is not None
    score = AnalystTracker.credibility(rows)
    assert 0 <= score["credibility_score"] <= 100
    assert score["tier"] in {"S", "A", "B", "C", "관찰중"}


def test_recent_unresolved_report_is_not_counted_as_a_miss():
    rows = AnalystTracker().evaluate_report(report(target=200), prices(periods=30))
    m3 = next(x for x in rows if x.horizon == "3m")
    assert m3.matured is False
    assert m3.hit is None
    metric = AnalystTracker.credibility(rows)
    assert metric["n_mature_target_reports"] == 0
    assert metric["n_pending_target_reports"] == 1
    assert metric["hit_rate"] is None


def test_sparse_sample_never_gets_inflated_tier():
    rows = AnalystTracker().evaluate_report(report(target=102), prices(periods=90))
    metric = AnalystTracker.credibility(rows)
    assert metric["n_evaluable"] <= 1
    assert metric["tier"] == "관찰중"
    assert metric["sample_confidence"] < 1


def test_completed_miss_is_counted_only_after_horizon():
    rows = AnalystTracker().evaluate_report(report(target=500), prices(periods=90))
    m3 = next(x for x in rows if x.horizon == "3m")
    assert m3.matured is True
    assert m3.hit is False
    assert m3.disparity_pct is not None


def test_bearish_target_uses_low_for_hit():
    rows = AnalystTracker().evaluate_report(
        report(target=98, rating="SELL"),
        prices(periods=90),
    )
    m1 = next(x for x in rows if x.horizon == "1m")
    assert m1.hit is True
    assert m1.direction == "BEARISH"


def test_rating_normalization():
    assert normalize_rating("Strong Buy") == "BUY"
    assert normalize_rating("중립") == "HOLD"
    assert normalize_rating("Underweight") == "SELL"
