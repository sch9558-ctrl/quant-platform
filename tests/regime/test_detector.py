import numpy as np
import pandas as pd
import pytest

from quant.regime.detector import BreadthStats, RegimeDetector, compute_breadth


def _make_index_df(annual_drift: float, annual_vol: float, n: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    daily_drift = annual_drift / 252
    daily_vol = annual_vol / np.sqrt(252)
    rets = rng.normal(daily_drift, daily_vol, n)
    close = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                          "volume": 1_000_000}, index=idx)


def test_strong_uptrend_classified_bull_lowvol():
    df = _make_index_df(annual_drift=0.35, annual_vol=0.08, seed=1)
    detector = RegimeDetector("korea")
    result = detector.detect(df)
    assert result.trend_regime == "bull"
    assert result.index_return_6m > 0


def test_strong_downtrend_classified_bear():
    df = _make_index_df(annual_drift=-0.35, annual_vol=0.08, seed=2)
    detector = RegimeDetector("korea")
    result = detector.detect(df)
    assert result.trend_regime == "bear"
    assert result.index_return_6m < 0


def test_flat_market_classified_sideways():
    # deterministic tight oscillation around a flat mean, rather than a
    # driftless random walk (which can easily wander >5% over any given
    # 6-month window purely by chance) -- this guarantees a small, bounded
    # 6-month return regardless of random seed.
    n = 500
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(3)
    # tiny mean-zero noise around a perfectly flat level, so both the 6m
    # return and the price-vs-moving-average relationship stay within the
    # sideways band regardless of random seed
    close = 100 + rng.normal(0, 0.05, n)
    df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                        "volume": 1_000_000}, index=idx)
    detector = RegimeDetector("korea")
    result = detector.detect(df)
    assert result.trend_regime == "sideways"


def test_high_vol_period_flagged():
    # first half calm, second half a volatility spike -> percentile of the
    # trailing 20d vol at the end should look elevated relative to its own
    # rolling history
    calm = _make_index_df(annual_drift=0.05, annual_vol=0.06, n=400, seed=4)
    rng = np.random.default_rng(5)
    shock_rets = rng.normal(0, 0.55 / np.sqrt(252), 60)
    shock_close = calm["close"].iloc[-1] * np.exp(np.cumsum(shock_rets))
    shock_idx = pd.bdate_range(calm.index[-1] + pd.Timedelta(days=1), periods=60)
    shock_df = pd.DataFrame({"open": shock_close, "high": shock_close, "low": shock_close,
                              "close": shock_close, "volume": 1_000_000}, index=shock_idx)
    combined = pd.concat([calm, shock_df])

    detector = RegimeDetector("korea")
    result = detector.detect(combined)
    assert result.volatility_regime == "high_vol"


def test_breadth_computation():
    idx = pd.bdate_range("2023-01-01", periods=30)
    up = pd.DataFrame({"close": np.linspace(100, 130, 30)}, index=idx)
    down = pd.DataFrame({"close": np.linspace(100, 70, 30)}, index=idx)
    breadth = compute_breadth({"UP": up, "DOWN": down})
    assert breadth.advances == 1
    assert breadth.declines == 1
    assert breadth.adv_dec_ratio == pytest.approx(0.5)


def test_summary_label_format():
    df = _make_index_df(annual_drift=0.3, annual_vol=0.07, seed=6)
    result = RegimeDetector("us").detect(df)
    label = result.summary_label()
    assert "/" in label and label.count("/") == 2


def test_risk_off_when_breadth_and_vol_bad():
    df = _make_index_df(annual_drift=-0.25, annual_vol=0.5, seed=7)
    bad_breadth = BreadthStats(advances=10, declines=90, adv_dec_ratio=0.1,
                                new_highs=1, new_lows=50, nh_nl_ratio=0.02)
    result = RegimeDetector("korea").detect(df, breadth=bad_breadth)
    assert result.risk_regime == "risk_off"
