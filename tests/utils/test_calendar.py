import pandas as pd

from quant.utils import calendar as cal


def test_weekend_is_not_a_trading_day():
    assert cal.is_trading_day("2026-08-15", "korea") is False  # Saturday
    assert cal.is_trading_day("2026-08-16", "korea") is False  # Sunday


def test_korea_substitute_holiday_is_recognized():
    # 2026-08-15 (Liberation Day) falls on a Saturday; KRX observes a
    # substitute holiday on the next business day (2026-08-17, Monday).
    # A naive weekday-only calendar would incorrectly call this a trading day.
    assert cal.is_trading_day("2026-08-17", "korea") is False


def test_ordinary_weekday_is_a_trading_day():
    assert cal.is_trading_day("2026-08-18", "korea") is True
    assert cal.is_trading_day("2026-08-18", "us") is True


def test_trading_days_excludes_weekends_and_holidays():
    days = cal.trading_days("2026-08-01", "2026-08-31", "korea")
    assert pd.Timestamp("2026-08-15") not in days  # Saturday
    assert pd.Timestamp("2026-08-17") not in days  # substitute holiday
    assert pd.Timestamp("2026-08-18") in days


def test_us_and_korea_calendars_differ():
    # Chuseok (Korean Thanksgiving) is a KRX holiday but an ordinary US
    # trading day -- the two markets must not share one calendar.
    kr_days = set(cal.trading_days("2026-09-01", "2026-09-30", "korea"))
    us_days = set(cal.trading_days("2026-09-01", "2026-09-30", "us"))
    assert kr_days != us_days


def test_last_n_trading_days_returns_exactly_n():
    days = cal.last_n_trading_days("2026-08-26", 10, "korea")
    assert len(days) == 10
    assert days[-1] == pd.Timestamp("2026-08-26")
    assert days.is_monotonic_increasing


def test_latest_completed_session_on_a_holiday_rolls_back():
    # as_of a Korean holiday -> latest completed session is the prior trading day
    session = cal.latest_completed_session("korea", "2026-08-17")  # substitute holiday
    assert session == pd.Timestamp("2026-08-14")


def test_latest_completed_session_on_a_trading_day_is_itself():
    session = cal.latest_completed_session("korea", "2026-08-18")
    assert session == pd.Timestamp("2026-08-18")


def test_missing_sessions_excludes_holidays_and_flags_real_gaps():
    all_days = cal.trading_days("2026-08-01", "2026-08-31", "korea")
    # simulate a provider that returned everything except two real sessions
    present = all_days.delete([2, 5])
    missing = cal.missing_sessions(present, "2026-08-01", "2026-08-31", "korea")
    assert len(missing) == 2
    assert pd.Timestamp("2026-08-15") not in missing  # weekend, not "missing"
    assert pd.Timestamp("2026-08-17") not in missing  # holiday, not "missing"


def test_missing_sessions_empty_when_nothing_missing():
    all_days = cal.trading_days("2026-08-01", "2026-08-31", "korea")
    missing = cal.missing_sessions(all_days, "2026-08-01", "2026-08-31", "korea")
    assert len(missing) == 0
