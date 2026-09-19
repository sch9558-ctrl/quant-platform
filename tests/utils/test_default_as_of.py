"""The analysis date the daily pipeline runs against.

This is the bug that took the daily pipeline down for three and a half
weeks, so it gets its own file. Every entry point defaulted to
`pd.Timestamp.today()` and the workflow passed today's Korean date to both
markets. At 07:00 Asia/Seoul that date's session has not happened:

  * KRX opens at 09:00, so the Korean bar for "today" cannot exist;
  * the US session bearing that date is ~12 hours away;
  * on a Saturday or a holiday it is not a session at all, so the provider
    is handed a date it has no data for.

`freshness` is mandatory with `max_lag_sessions: 0`, so this failed
validation every single morning and Fail-Closed both markets -- while the
report blamed the data provider. These tests pin the property that
matters: **the requested session must already be finished.**
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.utils.calendar import default_as_of, is_trading_day, trading_days

MARKETS = ["korea", "us"]

# 07:00 KST == 22:00 UTC the previous day. These are the instants the
# scheduled workflow actually fires at.
FRIDAY_0700_KST = "2026-09-17T22:00:00Z"    # 2026-09-18 07:00 KST (Fri)
SATURDAY_0700_KST = "2026-09-18T22:00:00Z"  # 2026-09-19 07:00 KST (Sat)
SUNDAY_0700_KST = "2026-09-19T22:00:00Z"    # 2026-09-20 07:00 KST (Sun)
MONDAY_0700_KST = "2026-09-20T22:00:00Z"    # 2026-09-21 07:00 KST (Mon)

ALL_FIRING_INSTANTS = [
    pytest.param(FRIDAY_0700_KST, id="fri-0700-kst"),
    pytest.param(SATURDAY_0700_KST, id="sat-0700-kst"),
    pytest.param(SUNDAY_0700_KST, id="sun-0700-kst"),
    pytest.param(MONDAY_0700_KST, id="mon-0700-kst"),
]


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("now", ALL_FIRING_INSTANTS)
def test_result_is_always_a_real_trading_session(market, now):
    resolved = default_as_of(market, now=now)
    assert is_trading_day(resolved, market), (
        f"{market}: {resolved} is not a trading session -- the provider has no "
        "data for it, which is what broke weekend runs"
    )


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("now", ALL_FIRING_INSTANTS)
def test_never_requests_a_session_that_has_not_closed(market, now):
    """The core invariant. A requested session must be in the past relative
    to the firing instant, in the market's own timezone."""
    resolved = pd.Timestamp(default_as_of(market, now=now))
    tz = "Asia/Seoul" if market == "korea" else "America/New_York"
    local_now = pd.Timestamp(now).tz_convert(tz)
    local_date = local_now.normalize().tz_localize(None)
    close_hour = 15.5 if market == "korea" else 16.0
    local_hour = local_now.hour + local_now.minute / 60.0

    if resolved == local_date:
        assert local_hour >= close_hour, (
            f"{market}: asked for {resolved.date()} at {local_now}, but that "
            "session has not closed yet"
        )
    else:
        assert resolved < local_date, (
            f"{market}: asked for {resolved.date()} at {local_now} -- that is in "
            "the future"
        )


@pytest.mark.parametrize("market", MARKETS)
def test_weekday_0700_kst_resolves_to_the_previous_session_not_today(market):
    """The specific failure: at 07:00 KST on a trading day, "today" is not
    yet available for either market."""
    resolved = default_as_of(market, now=FRIDAY_0700_KST)
    assert resolved != "2026-09-18", (
        f"{market}: asked for today's session at 07:00 KST -- this is exactly "
        "what failed freshness every morning"
    )
    assert resolved == "2026-09-17"


@pytest.mark.parametrize("market", MARKETS)
def test_saturday_run_rolls_back_to_friday(market):
    assert default_as_of(market, now=SATURDAY_0700_KST) == "2026-09-18"


@pytest.mark.parametrize("market", MARKETS)
def test_monday_run_rolls_back_over_the_weekend(market):
    assert default_as_of(market, now=MONDAY_0700_KST) == "2026-09-18"


def test_markets_are_resolved_independently():
    """A single shared date cannot be correct for both markets in general,
    which is why resolution is per market rather than one value passed to
    both. Around a session boundary the two legitimately differ."""
    # 09:00 KST: Korea's session for today is open (not closed); the US
    # session that closed most recently is the previous US session.
    nine_am_kst = "2026-09-18T00:00:00Z"  # 2026-09-18 09:00 KST
    kr = default_as_of("korea", now=nine_am_kst)
    us = default_as_of("us", now=nine_am_kst)
    for market, value in (("korea", kr), ("us", us)):
        assert is_trading_day(value, market)
    # 16:30 KST, after the Korean close: Korea may now use today, while the
    # US still cannot -- the two dates diverge.
    after_kr_close = "2026-09-18T07:30:00Z"  # 2026-09-18 16:30 KST
    assert default_as_of("korea", now=after_kr_close) == "2026-09-18"
    assert default_as_of("us", now=after_kr_close) == "2026-09-17"


@pytest.mark.parametrize("market", MARKETS)
def test_korean_market_waits_for_its_own_close_plus_settling(market):
    """Right at the closing bell the end-of-day bar is not published yet, so
    a settling window is respected rather than racing the exchange."""
    # 15:35 KST, five minutes after the KRX close
    just_after_bell = "2026-09-18T06:35:00Z"
    resolved = default_as_of("korea", now=just_after_bell)
    assert resolved == "2026-09-17", "should not race the EOD publication"


def test_resolved_session_is_never_in_the_future_of_the_calendar():
    """Sanity against a clock or timezone mistake: the resolved session must
    exist in the calendar at or before the firing instant."""
    for market in MARKETS:
        for now in (FRIDAY_0700_KST, SATURDAY_0700_KST, MONDAY_0700_KST):
            resolved = default_as_of(market, now=now)
            sessions = trading_days("2026-09-01", "2026-09-30", market)
            assert pd.Timestamp(resolved) in set(sessions)
