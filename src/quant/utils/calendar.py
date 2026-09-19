"""Trading-calendar helpers backed by real exchange holiday schedules.

Uses `pandas_market_calendars` (XKRX for Korea, NYSE for the US -- NYSE and
NASDAQ share the same US equity holiday calendar) rather than a
weekday-only approximation. This matters a great deal for the Data Quality
Engine's missing-data and freshness checks (spec sections 6-7): a
weekend/holiday with no data is *not* missing data, and "the last completed
trading session" is not simply "yesterday" around a long weekend.

Every public function here is a thin, cached wrapper around
`pandas_market_calendars` so the rest of the codebase never has to import
it directly or reason about calendar internals.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal

_CALENDAR_NAME = {"korea": "XKRX", "us": "NYSE"}

# A safety net if a market's calendar can't be loaded for some reason (e.g.
# an unexpected upstream data issue in the calendar library) -- degrade to
# weekday-only rather than crash the whole pipeline. This is logged loudly
# by callers, not silently swallowed, since it weakens the missing-data
# guarantee this module exists to provide.
_FALLBACK_WEEKDAY_ONLY = False


def _to_date(d: date | datetime | str | pd.Timestamp) -> date:
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    if isinstance(d, pd.Timestamp):
        return d.date()
    if isinstance(d, datetime):
        return d.date()
    return d


@lru_cache(maxsize=None)
def _calendar(market: str):
    assert market in _CALENDAR_NAME, f"Unknown market: {market!r}"
    return mcal.get_calendar(_CALENDAR_NAME[market])


@lru_cache(maxsize=8)
def _valid_days_cache_key(market: str, start: str, end: str) -> tuple:
    cal = _calendar(market)
    schedule = cal.schedule(start_date=start, end_date=end)
    return tuple(d.date() for d in schedule.index)


def is_trading_day(d: date | datetime | str, market: str) -> bool:
    d = _to_date(d)
    days = _valid_days_cache_key(market, (d - pd.Timedelta(days=10)).isoformat(), (d + pd.Timedelta(days=10)).isoformat())
    return d in days


def trading_days(start: str, end: str, market: str) -> pd.DatetimeIndex:
    """All real trading sessions (exchange holidays excluded) in [start, end]."""
    days = _valid_days_cache_key(market, start, end)
    return pd.DatetimeIndex(sorted(days))


def last_n_trading_days(end: str, n: int, market: str) -> pd.DatetimeIndex:
    end_ts = pd.Timestamp(end)
    # over-fetch calendar days then trim to the last n real sessions
    start = (end_ts - pd.Timedelta(days=int(n * 2.2) + 20)).strftime("%Y-%m-%d")
    days = trading_days(start, end, market)
    return days[-n:]


def latest_completed_session(market: str, as_of: date | datetime | str | pd.Timestamp | None = None) -> pd.Timestamp:
    """The most recent trading session that should already have a complete
    end-of-day bar as of `as_of` (default: now, in the market's own
    timezone). Used by the Freshness check (spec section 7): if today is a
    Korean holiday, "latest Korea trading session" is the prior session,
    not today and not a naive "yesterday"."""
    tz = "Asia/Seoul" if market == "korea" else "America/New_York"
    now = pd.Timestamp(as_of).tz_localize(None) if as_of is not None else pd.Timestamp.now(tz=tz).tz_localize(None)
    days = trading_days((now - pd.Timedelta(days=20)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), market)
    if len(days) == 0:
        raise ValueError(f"No trading sessions found for market={market!r} near as_of={as_of!r}")
    return days[-1]


#: Local closing time per market, and how long after the close end-of-day
#: data is realistically published. `latest_completed_session` answers "the
#: last session on or before this DATE"; these let us answer the different
#: question "the last session that has actually finished by this INSTANT".
_MARKET_TZ = {"korea": "Asia/Seoul", "us": "America/New_York"}
_MARKET_CLOSE_HOUR = {"korea": 15.5, "us": 16.0}          # local wall clock
_DEFAULT_SETTLE_HOURS = 1.0                                # EOD publication lag


def latest_closed_session(
    market: str,
    now: pd.Timestamp | str | None = None,
    settle_hours: float = _DEFAULT_SETTLE_HOURS,
) -> pd.Timestamp:
    """The most recent session that has actually CLOSED as of `now`.

    This differs from `latest_completed_session` in a way that matters
    every single morning: that function takes a *date* and returns the last
    session on or before it, which is correct when you already know which
    calendar date you mean. But the daily pipeline runs at 07:00
    **Asia/Seoul**, and at that instant the US session bearing today's
    Korean date has not opened, let alone closed -- the newest US data that
    can possibly exist is the previous US session.

    Passing the Korean date straight through therefore makes the US market
    look permanently one session stale, which (with `max_lag_sessions: 0`)
    would Fail-Closed the US market every morning and blame the data
    provider for it.

    So this resolves the instant in the market's own timezone and drops
    today's session if it has not yet closed (plus a small settling window
    for end-of-day data to be published).
    """
    tz = _MARKET_TZ[market]
    now_ts = pd.Timestamp.now(tz=tz) if now is None else pd.Timestamp(now)
    if now_ts.tzinfo is None:
        # A naive instant is interpreted as UTC rather than as local time:
        # callers pass wall-clock "now" from a CI runner, which is UTC.
        now_ts = now_ts.tz_localize("UTC")
    local = now_ts.tz_convert(tz)

    cutoff = _MARKET_CLOSE_HOUR[market] + settle_hours
    local_hour = local.hour + local.minute / 60.0

    candidate_date = local.normalize().tz_localize(None)
    days = trading_days(
        (candidate_date - pd.Timedelta(days=20)).strftime("%Y-%m-%d"),
        candidate_date.strftime("%Y-%m-%d"),
        market,
    )
    if len(days) == 0:
        raise ValueError(f"No trading sessions found for market={market!r} near {local!r}")

    # If the newest candidate is today and today's close (+ settle) has not
    # passed yet, today's bar does not exist yet -- step back one session.
    if days[-1].normalize() == candidate_date and local_hour < cutoff:
        if len(days) < 2:
            raise ValueError(f"No closed session yet for market={market!r} near {local!r}")
        return days[-2]
    return days[-1]


def default_as_of(market: str, now: pd.Timestamp | str | None = None) -> str:
    """The session the daily pipeline should analyse for this market.

    Every entry point used to default to `pd.Timestamp.today()`, which is
    wrong in two compounding ways and broke the daily run outright:

    * It is the **runner's** today (UTC on CI), not the market's.
    * More importantly, "today" is not a *finished* session. The pipeline
      fires at 07:00 Asia/Seoul, when the Korean session bearing that date
      has not opened (KRX opens 09:00) and the US session bearing it is
      still 12 hours away. Asking a provider for data "as of today" at that
      hour requests a bar that cannot exist yet, so `freshness` --
      mandatory, `max_lag_sessions: 0` -- fails, and Fail-Closed blocks the
      market. Every morning. With a report blaming the data provider.
      On a weekend it is worse: the date is not a session at all, so the
      provider is handed a date it has no data for in the first place.

    Resolving per market instead of passing one date to both is not a
    detail: at 07:00 KST the correct Korean session and the correct US
    session are frequently different dates, and a single shared `as_of`
    cannot be right for both.
    """
    return latest_closed_session(market, now=now).strftime("%Y-%m-%d")


def expected_sessions_between(start: str, end: str, market: str) -> pd.DatetimeIndex:
    """Alias for `trading_days`, named for clarity at missing-data call
    sites: "the sessions we expect to have a row for"."""
    return trading_days(start, end, market)


def missing_sessions(present_dates: pd.DatetimeIndex, start: str, end: str, market: str) -> pd.DatetimeIndex:
    """Real trading sessions in [start, end] that are absent from
    `present_dates` -- the Missing Data check (spec section 6). Exchange
    holidays are never reported as missing."""
    expected = expected_sessions_between(start, end, market).normalize()
    present = pd.DatetimeIndex(present_dates).normalize()
    return expected.difference(present)
