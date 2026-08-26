import numpy as np
import pandas as pd
import pytest

from quant.features import mean_reversion as mr
from quant.features import momentum as mom
from quant.features import price as price_feat
from quant.features import trend
from quant.features import volatility as vol
from quant.features import volume as volu


@pytest.fixture
def close():
    idx = pd.bdate_range("2022-01-03", periods=100)
    rng = np.random.default_rng(0)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 100)))
    return pd.Series(prices, index=idx, name="close")


@pytest.fixture
def ohlcv(close):
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.random.default_rng(1).integers(1000, 5000, len(close)),
    }, index=close.index)


def test_sma_matches_manual_rolling_mean(close):
    result = trend.sma(close, 10)
    expected = close.rolling(10).mean()
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_roc_formula(close):
    result = mom.roc(close, 5)
    expected = close / close.shift(5) - 1
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_rsi_bounded_between_0_and_100(close):
    result = mom.rsi(close, 14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_zscore_manual_check(close):
    result = mr.zscore(close, 20)
    window = close.iloc[0:20]
    manual = (close.iloc[19] - window.mean()) / window.std()
    assert abs(result.iloc[19] - manual) < 1e-9


def test_bollinger_position_mostly_in_unit_range(close):
    pos = mr.bollinger_position(close, 20).dropna()
    # not strictly bounded (price can pierce the bands) but should be
    # centered near [0, 1] for the vast majority of observations
    assert pos.between(-0.5, 1.5).mean() > 0.9


def test_ma_cross_event_fires_only_at_transitions(close):
    result = trend.ma_cross(close, 5, 20)
    events = result[f"ma_cross_event_5_20"].dropna()
    signal = result[f"ma_cross_signal_5_20"].dropna()
    for date in events[events != 0].index:
        loc = signal.index.get_loc(date)
        if loc == 0:
            continue
        assert signal.iloc[loc] != signal.iloc[loc - 1]


def test_historical_volatility_nonnegative(close):
    hv = vol.historical_volatility(close, 20).dropna()
    assert (hv >= 0).all()


def test_downside_volatility_leq_total_volatility(close):
    hv = vol.historical_volatility(close, 20)
    dv = vol.downside_volatility(close, 20)
    both = pd.concat([hv, dv], axis=1).dropna()
    assert (both.iloc[:, 1] <= both.iloc[:, 0] + 1e-9).all()


def test_volume_ratio_around_one_on_average(ohlcv):
    vr = volu.volume_ratio(ohlcv["volume"], 20).dropna()
    assert 0.5 < vr.mean() < 2.0


def test_simple_returns_columns(close):
    df = price_feat.simple_returns(close, (1, 5, 20))
    assert list(df.columns) == ["ret_1d", "ret_5d", "ret_20d"]
    assert df["ret_1d"].dropna().iloc[0] == pytest.approx(close.iloc[1] / close.iloc[0] - 1)
