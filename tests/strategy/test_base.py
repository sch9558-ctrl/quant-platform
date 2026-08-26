import pandas as pd

from quant.strategy.base import cross_sectional_select, stateful_long_flat


def test_stateful_long_flat_basic_cycle():
    idx = pd.bdate_range("2022-01-01", periods=6)
    entry = pd.Series([False, True, False, False, False, False], index=idx)
    exit_ = pd.Series([False, False, False, True, False, False], index=idx)
    pos = stateful_long_flat(entry, exit_)
    assert list(pos) == [0, 1, 1, 0, 0, 0]


def test_stateful_long_flat_reenters_after_exit():
    idx = pd.bdate_range("2022-01-01", periods=8)
    entry = pd.Series([False, True, False, False, False, True, False, False], index=idx)
    exit_ = pd.Series([False, False, True, False, False, False, False, True], index=idx)
    pos = stateful_long_flat(entry, exit_)
    assert list(pos) == [0, 1, 0, 0, 0, 1, 1, 0]


def test_cross_sectional_select_picks_top_fraction():
    idx = pd.bdate_range("2022-01-01", periods=2)
    scores = pd.DataFrame({
        "A": [1.0, 5.0], "B": [2.0, 4.0], "C": [3.0, 3.0], "D": [4.0, 2.0], "E": [5.0, 1.0],
    }, index=idx)
    weights = cross_sectional_select(scores, top_pct=0.4)  # top 2 of 5
    row0 = weights.iloc[0]
    assert (row0 > 0).sum() == 2
    assert row0["E"] == row0["D"]  # equal-weighted among selected
    assert abs(row0.sum() - 1.0) < 1e-9


def test_cross_sectional_select_handles_nan():
    idx = pd.bdate_range("2022-01-01", periods=1)
    scores = pd.DataFrame({"A": [1.0], "B": [float("nan")], "C": [3.0]}, index=idx)
    weights = cross_sectional_select(scores, top_pct=0.5, min_names=1)
    assert weights.iloc[0]["B"] == 0.0
    assert weights.iloc[0].sum() <= 1.0 + 1e-9
