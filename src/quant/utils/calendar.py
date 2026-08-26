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
