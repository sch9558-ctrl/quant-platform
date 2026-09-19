"""Publication gate: synthetic or stale data must never reach production.

The first test here is a direct reproduction of the failure that made
this module necessary -- a payload stamped `generated_at` today while
describing 2022-06-01, published with a headline of DATA INTEGRITY PASS.
Every component was behaving as designed; nothing was responsible for
noticing that the payload did not describe the current market at all.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.dashboard_export import publishability as P
from quant.dashboard_export.export import write_dashboard_json

# 07:00 KST on 2026-08-26 -- the instant the daily pipeline actually runs.
# Expressed in UTC on purpose: this is what a CI runner's clock reads, and
# the whole point of the market-aware resolution is that this one instant
# maps to a DIFFERENT expected session per market.
NOW = "2026-08-25T22:00:00Z"


def _payload(**overrides) -> dict:
    report = P.assess(
        overrides.pop("mode", P.REAL),
        {"korea": overrides.pop("korea", "2026-08-25"), "us": overrides.pop("us", "2026-08-25")},
        now=NOW,
    )
    data = {
        "schema_version": 2,
        "generated_at": "2026-08-26T07:04:00+00:00",
        "as_of": "2026-08-26",
        "data_source_mode": report.data_source_mode,
        "publishability": report.to_dict(),
        "overview": {"data_integrity": "PASS"},
        "data_quality": {},
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------
# The original failure
# --------------------------------------------------------------------
def test_four_year_old_data_stamped_today_is_not_publishable():
    """generated_at 2026-08-26 + as_of 2022-06-01 + DATA INTEGRITY PASS.

    This exact combination was live on the public dashboard. It must be
    impossible to publish, regardless of what the data-quality engine
    concluded about the (synthetic, four-year-old) dataset itself.
    """
    report = P.assess(P.SYNTHETIC, {"korea": "2022-06-01", "us": "2022-06-01"}, now=NOW)

    assert not report.publishable
    assert not report.is_real
    assert report.markets["korea"].status == P.STALE
    assert report.markets["korea"].gap_sessions is not None
    assert report.markets["korea"].gap_sessions > 500, "four years of sessions"
    # and the reason a human reads must name both problems
    joined = " ".join(report.reasons)
    assert "합성" in joined
    assert "최신 거래일까지 갱신되지 않았습니다" in joined


def test_write_refuses_the_original_failure_payload(tmp_path):
    data = _payload(mode=P.SYNTHETIC, korea="2022-06-01", us="2022-06-01")
    with pytest.raises(P.NotPublishableError):
        write_dashboard_json(data, tmp_path)
    assert not (tmp_path / "dashboard.json").exists(), "nothing may be written on refusal"


# --------------------------------------------------------------------
# Synthetic detection
# --------------------------------------------------------------------
def test_synthetic_data_is_never_publishable_even_when_perfectly_fresh():
    """Freshness does not redeem synthetic data. A demo run produced today,
    describing today's session, is still not a description of the market."""
    report = P.assess(P.SYNTHETIC, {"korea": "2026-08-25", "us": "2026-08-25"}, now=NOW)

    assert report.all_fresh
    assert not report.publishable


def test_real_and_fresh_is_publishable(tmp_path):
    data = _payload()
    assert data["publishability"]["publishable"] is True
    path = write_dashboard_json(data, tmp_path)
    assert path.exists()


# --------------------------------------------------------------------
# Freshness, counted on the exchange calendar
# --------------------------------------------------------------------
def test_monday_morning_holding_fridays_bar_is_fresh_not_three_days_stale():
    """The gap is counted in sessions on the exchange calendar, so a Monday
    run holding Friday's bar is current -- otherwise every Monday, and every
    day after a holiday, would read as a data failure."""
    monday_0700_kst = "2026-08-23T22:00:00Z"  # 2026-08-24 07:00 KST, a Monday
    friday = P.latest_closed_session("us", now=monday_0700_kst)
    assert friday.dayofweek == 4, "sanity: the last closed US session is a Friday"

    fresh = P.assess_market_freshness("us", friday.strftime("%Y-%m-%d"), now=monday_0700_kst)
    assert fresh.status == P.FRESH
    assert fresh.gap_sessions == 0


def test_us_session_is_resolved_in_us_time_not_korean_time():
    """At 07:00 KST the US session bearing today's Korean date has not even
    opened. Expecting it would Fail-Closed the US market every morning and
    blame the provider -- this is the bug this resolution exists to prevent."""
    korea = P.latest_closed_session("korea", now=NOW)
    us = P.latest_closed_session("us", now=NOW)

    assert str(korea.date()) == "2026-08-25"
    assert str(us.date()) == "2026-08-25"
    # Neither market may expect the Korean calendar date of the run itself.
    assert str(korea.date()) != "2026-08-26"
    assert str(us.date()) != "2026-08-26"


def test_holidays_do_not_count_as_stale_sessions():
    """The gap must be measured on the exchange's own calendar, so a
    holiday week cannot make fresh data look stale."""
    expected = P.latest_closed_session("korea", now=NOW)
    fresh = P.assess_market_freshness("korea", expected.strftime("%Y-%m-%d"), now=NOW)
    assert fresh.status == P.FRESH
    assert fresh.gap_sessions == 0


def test_one_session_behind_is_stale_with_an_actionable_reason():
    expected = P.latest_closed_session("us", now=NOW)
    sessions = P.trading_days(
        (expected - pd.Timedelta(days=20)).strftime("%Y-%m-%d"),
        expected.strftime("%Y-%m-%d"), "us")
    previous = sessions[-2]

    report = P.assess(P.REAL, {"us": previous.strftime("%Y-%m-%d")}, now=NOW)

    assert not report.publishable
    assert report.markets["us"].status == P.STALE
    assert report.markets["us"].gap_sessions == 1
    reason = report.reasons[0]
    # the human-facing reason has to carry expected/actual/gap, not just "FAIL"
    assert "예상 최신 거래일" in reason and "실제 최신 거래일" in reason and "1거래일" in reason


def test_data_dated_in_the_future_is_flagged_not_treated_as_extra_fresh():
    report = P.assess(P.REAL, {"korea": "2027-01-04"}, now=NOW)
    assert report.markets["korea"].status == P.UNKNOWN
    assert not report.publishable


def test_missing_session_is_unknown_not_fresh():
    report = P.assess(P.REAL, {"korea": None}, now=NOW)
    assert report.markets["korea"].status == P.UNKNOWN
    assert not report.publishable


# --------------------------------------------------------------------
# The escape hatch must stay an escape hatch
# --------------------------------------------------------------------
def test_allow_unpublishable_writes_but_keeps_the_marker(tmp_path):
    """Local development can write synthetic data, but the payload must
    still say so -- the file itself must never lie about its own status."""
    import json

    data = _payload(mode=P.SYNTHETIC)
    path = write_dashboard_json(data, tmp_path, allow_unpublishable=True)
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["data_source_mode"] == P.SYNTHETIC
    assert written["publishability"]["publishable"] is False
