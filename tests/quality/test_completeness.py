import pandas as pd

from quant import config
from quant.quality.completeness import (
    validate_duplicates,
    validate_freshness,
    validate_missing_sessions,
    validate_timezone,
)
from tests.quality.conftest import make_records

CFG = config.quality_config()


def test_clean_records_have_no_duplicates(clean_records):
    result = validate_duplicates(clean_records, "korea", CFG)
    assert result.passed


def test_duplicate_symbol_date_key_fails():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 105, "low": 98, "close": 102, "volume": 1000},
        {"symbol": "A", "date": "2026-08-03", "open": 101, "high": 106, "low": 99, "close": 103, "volume": 1100},
    ])
    result = validate_duplicates(df, "korea", CFG)
    assert not result.passed
    assert result.details["duplicate_rows"] == 2


def test_clean_records_have_no_missing_sessions(clean_records):
    result = validate_missing_sessions(clean_records, "korea", "2026-08-03", "2026-08-12", CFG)
    assert result.passed


def test_gap_in_the_middle_is_a_missing_session():
    # 8 trading days requested, but one weekday (2026-08-06) is missing
    dates = [d for d in pd.bdate_range("2026-08-03", periods=8) if d != pd.Timestamp("2026-08-06")]
    rows = [{"symbol": "A", "date": d.strftime("%Y-%m-%d"), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for d in dates]
    df = make_records(rows)
    result = validate_missing_sessions(df, "korea", "2026-08-03", "2026-08-12", CFG)
    assert not result.passed
    assert result.details["total_missing_sessions"] == 1


def test_weekend_and_holiday_are_not_missing_sessions():
    # Aug 2026: 08-15 is Saturday, 08-17 is a substitute holiday in Korea.
    # A provider that simply has no rows for those two dates should NOT
    # be flagged -- only real trading-day gaps count.
    dates = pd.bdate_range("2026-08-10", "2026-08-21")
    dates = [d for d in dates if d not in (pd.Timestamp("2026-08-17"),)]  # KRX doesn't trade on the substitute holiday
    rows = [{"symbol": "A", "date": d.strftime("%Y-%m-%d"), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for d in dates]
    df = make_records(rows)
    result = validate_missing_sessions(df, "korea", "2026-08-10", "2026-08-21", CFG)
    assert result.passed


def test_missing_before_listing_date_is_allowed():
    dates = pd.bdate_range("2026-08-10", periods=5)  # symbol only listed from the 3rd date onward
    rows = [{"symbol": "NEWCO", "date": d.strftime("%Y-%m-%d"), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for d in dates[2:]]
    df = make_records(rows)
    result = validate_missing_sessions(
        df, "korea", "2026-08-10", dates[-1].strftime("%Y-%m-%d"), CFG,
        listing_dates={"NEWCO": dates[2]},
    )
    assert result.passed


def test_freshness_passes_when_data_is_current_as_of_latest_session():
    df = make_records([
        {"symbol": "A", "date": "2026-08-18", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
    ])
    result = validate_freshness(df, "korea", "2026-08-18", CFG)
    assert result.passed


def test_freshness_fails_when_data_is_stale():
    df = make_records([
        {"symbol": "A", "date": "2026-08-10", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
    ])
    result = validate_freshness(df, "korea", "2026-08-18", CFG)
    assert not result.passed
    assert result.details["lag_sessions"] > 0


def test_freshness_on_a_holiday_rolls_back_expectation():
    # as_of a KRX holiday -> the latest *expected* session is the prior
    # trading day, so data current through that day should still PASS.
    df = make_records([
        {"symbol": "A", "date": "2026-08-14", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
    ])
    result = validate_freshness(df, "korea", "2026-08-17", CFG)  # 08-17 is the substitute holiday
    assert result.passed


def test_clean_records_have_valid_timezone(clean_records):
    result = validate_timezone(clean_records, "korea", CFG)
    assert result.passed


def test_naive_retrieved_at_fails():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
         "retrieved_at": "2026-08-03T09:00:00"},  # no timezone
    ])
    result = validate_timezone(df, "korea", CFG)
    assert not result.passed
