import pandas as pd

from quant import config
from quant.quality.ohlc import classify_outliers, validate_ohlc_integrity
from tests.quality.conftest import make_records


def test_clean_records_pass_ohlc_integrity(clean_records):
    result = validate_ohlc_integrity(clean_records, "korea")
    assert result.passed


def test_high_less_than_low_is_fatal():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 90, "low": 95, "close": 98, "volume": 1000},
    ])
    result = validate_ohlc_integrity(df, "korea")
    assert not result.passed
    assert any("high < low" in i.message for i in result.issues)


def test_high_less_than_open_is_fatal():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 110, "high": 105, "low": 100, "close": 103, "volume": 1000},
    ])
    result = validate_ohlc_integrity(df, "korea")
    assert not result.passed


def test_negative_volume_is_fatal():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 105, "low": 98, "close": 102, "volume": -5},
    ])
    result = validate_ohlc_integrity(df, "korea")
    assert not result.passed
    assert any("negative volume" in i.message for i in result.issues)


def test_zero_price_is_fatal():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 0, "high": 5, "low": 0, "close": 2, "volume": 1000},
    ])
    result = validate_ohlc_integrity(df, "korea")
    assert not result.passed
    assert any("non-positive price" in i.message for i in result.issues)


def test_empty_dataframe_passes_trivially():
    result = validate_ohlc_integrity(pd.DataFrame(), "korea")
    assert result.passed


def test_classify_outliers_normal_moves_are_valid(clean_records):
    classified, counts = classify_outliers(clean_records, config.quality_config())
    assert counts["REJECTED"] == 0
    assert counts["VALID"] == len(clean_records)


def test_classify_outliers_big_unexplained_move_is_rejected():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000},
        # -95% overnight with no recorded split/dividend -> REJECTED
        {"symbol": "A", "date": "2026-08-04", "open": 6, "high": 6, "low": 4, "close": 5, "volume": 1000},
    ])
    classified, counts = classify_outliers(df, config.quality_config())
    assert counts["REJECTED"] == 1
    row = classified[classified["date"] == pd.Timestamp("2026-08-04")].iloc[0]
    assert row["outlier_status"] == "REJECTED"


def test_classify_outliers_move_explained_by_corporate_action_is_downgraded():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000},
        {"symbol": "A", "date": "2026-08-04", "open": 6, "high": 6, "low": 4, "close": 5, "volume": 1000},
    ])
    ca_dates = {"A": {pd.Timestamp("2026-08-04")}}
    classified, counts = classify_outliers(df, config.quality_config(), ca_dates)
    assert counts["REJECTED"] == 0
    row = classified[classified["date"] == pd.Timestamp("2026-08-04")].iloc[0]
    assert row["outlier_status"] == "REVIEW"


def test_classify_outliers_moderate_move_is_review():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 102, "low": 99, "close": 100, "volume": 1000},
        {"symbol": "A", "date": "2026-08-04", "open": 55, "high": 62, "low": 54, "close": 60, "volume": 1000},  # -40%
    ])
    classified, counts = classify_outliers(df, config.quality_config())
    assert counts["REVIEW"] == 1
    assert counts["REJECTED"] == 0
