import numpy as np
import pandas as pd

from quant.data.quality import check_ohlcv


def _good_df(n=30):
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, n))
    close = np.abs(close) + 50
    df = pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.full(n, 100000),
    }, index=idx)
    df["adj_close"] = df["close"]
    return df


def test_clean_data_has_no_fatal_issues():
    df = _good_df()
    issues = check_ohlcv("TEST", df)
    assert all(i.severity != "FATAL" for i in issues)


def test_empty_frame_is_fatal():
    issues = check_ohlcv("TEST", pd.DataFrame())
    assert any(i.severity == "FATAL" and i.check == "missing_data" for i in issues)


def test_zero_price_is_fatal():
    df = _good_df()
    df.iloc[5, df.columns.get_loc("close")] = 0
    issues = check_ohlcv("TEST", df)
    assert any(i.check == "zero_or_negative_price" and i.severity == "FATAL" for i in issues)


def test_high_low_inversion_is_fatal():
    df = _good_df()
    df.iloc[3, df.columns.get_loc("high")] = df.iloc[3]["low"] - 1
    issues = check_ohlcv("TEST", df)
    assert any(i.check == "invalid_hl_range" and i.severity == "FATAL" for i in issues)


def test_abnormal_return_is_warning_not_fatal():
    df = _good_df()
    df.iloc[10, df.columns.get_loc("close")] = df.iloc[9]["close"] * 3
    issues = check_ohlcv("TEST", df, max_daily_return=0.35)
    matched = [i for i in issues if i.check == "abnormal_price_change"]
    assert matched and matched[0].severity == "WARNING"


def test_duplicate_dates_detected():
    df = _good_df()
    dup = pd.concat([df, df.iloc[[0]]])
    issues = check_ohlcv("TEST", dup)
    assert any(i.check == "duplicate_dates" for i in issues)


def test_negative_volume_is_fatal():
    df = _good_df()
    df.iloc[0, df.columns.get_loc("volume")] = -1
    issues = check_ohlcv("TEST", df)
    assert any(i.check == "negative_volume" and i.severity == "FATAL" for i in issues)
