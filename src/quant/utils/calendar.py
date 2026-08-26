"""Lightweight trading-calendar helpers.

Uses plain weekday business-day logic plus an optional holiday exclusion
file. This is intentionally simple (no extra dependency) -- if
`exchange_calendars`/`pandas_market_calendars` is installed later, swap the
implementation here without touching callers.

Holiday files (optional, JSON array of "YYYY-MM-DD" strings):
  data/cache/holidays_kr.json
  data/cache/holidays_us.json
If absent, only weekends are excluded (a reasonable approximation for
research purposes; exact market holidays matter most at execution time,
which is out of scope until live trading is enabled).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from quant import config


@lru_cache(maxsize=None)
def _holidays(market: str) -> set[date]:
    fname = "holidays_kr.json" if market == "korea" else "holidays_us.json"
    path = config.resolve_path(config.settings()["paths"]["data_cache"]) / fname
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {datetime.strptime(d, "%Y-%m-%d").date() for d in raw}


def is_trading_day(d: date | datetime | str, market: str) -> bool:
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    elif isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:
        return False
    return d not in _holidays(market)


def trading_days(start: str, end: str, market: str) -> pd.DatetimeIndex:
    all_days = pd.bdate_range(start, end)
    hol = _holidays(market)
    if not hol:
        return all_days
    return pd.DatetimeIndex([d for d in all_days if d.date() not in hol])


def last_n_trading_days(end: str, n: int, market: str) -> pd.DatetimeIndex:
    # over-fetch business days then trim to n, accounting for holidays
    days = pd.bdate_range(end=end, periods=n + 15)
    hol = _holidays(market)
    filtered = pd.DatetimeIndex([d for d in days if d.date() not in hol])
    return filtered[-n:]
