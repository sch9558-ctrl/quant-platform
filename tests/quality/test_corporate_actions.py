import pandas as pd

from quant.quality.corporate_actions import corporate_action_dates, validate_corporate_action_consistency
from tests.quality.conftest import make_records


def test_corporate_action_dates_extracted_from_split_and_dividend():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000, "split": 1.0},
        {"symbol": "A", "date": "2026-08-04", "open": 50, "high": 51, "low": 49, "close": 50, "volume": 1000, "split": 2.0},
        {"symbol": "B", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000, "dividend": 0.0},
        {"symbol": "B", "date": "2026-08-04", "open": 99, "high": 100, "low": 98, "close": 99, "volume": 1000, "dividend": 1.5},
    ])
    dates = corporate_action_dates(df)
    assert pd.Timestamp("2026-08-04") in dates["A"]
    assert pd.Timestamp("2026-08-03") not in dates["A"]
    assert pd.Timestamp("2026-08-04") in dates["B"]


def test_consistent_split_ratio_passes():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000, "split": 1.0},
        # 2:1 split -> close roughly halves
        {"symbol": "A", "date": "2026-08-04", "open": 50, "high": 51, "low": 49, "close": 50.5, "volume": 1000, "split": 2.0},
    ])
    result = validate_corporate_action_consistency(df, "korea")
    assert result.passed
    assert result.details["splits_checked"] == 1


def test_inconsistent_split_ratio_fails():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000, "split": 1.0},
        # recorded 2:1 split but the price barely moved -- looks unapplied
        {"symbol": "A", "date": "2026-08-04", "open": 99, "high": 100, "low": 98, "close": 99, "volume": 1000, "split": 2.0},
    ])
    result = validate_corporate_action_consistency(df, "korea")
    assert not result.passed


def test_no_splits_present_trivially_passes(clean_records):
    result = validate_corporate_action_consistency(clean_records, "korea")
    assert result.passed
    assert result.details["splits_checked"] == 0
