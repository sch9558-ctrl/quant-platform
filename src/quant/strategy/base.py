"""Common Strategy Interface (spec section 6).

Every strategy, regardless of family (trend/momentum/mean-reversion/
volatility/factor/multi-factor), implements `generate_weights` and returns a
single contract: a wide DataFrame indexed by date, one column per symbol,
whose values are *pre-normalization target weights* in [0, 1].

Weight semantics (read this before writing a new strategy):
  - A value of 1.0 means "this symbol alone would receive the strategy's
    full allocated capital if it were the only active signal that day."
  - Time-series strategies (moving-average cross, breakout, RSI reversal,
    ...) typically emit 0 or 1 per symbol per day, independently per
    symbol -- several symbols can be "1" on the same day.
  - Cross-sectional strategies (cross-sectional momentum, factor, multi-
    factor) typically emit 1/n_selected for each selected symbol and 0
    elsewhere, so each date's row already sums to <= 1.
  - The backtester (`backtest/engine.py`) rescales each date's row so it
    sums to at most 1.0 (excess is scaled down proportionally; any shortfall
    is left as cash) -- so a time-series strategy with 5 simultaneous "on"
    symbols ends up putting ~20% of capital in each, not 100% in each. This
    keeps every strategy family comparable under one allocation rule without
    forcing time-series strategies to know about position sizing.

No look-ahead: every strategy must compute its signal for date t using only
rows <= t of `ohlcv_map` (and, if used, `feature_map`/fundamental score
columns already computed causally by the Feature Engine). Do not use
`.shift(-n)` or any forward-looking transform inside a strategy.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    id: str = "base"
    family: str = "base"

    def __init__(self, **params):
        self.params = params

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.params})"

    @abstractmethod
    def generate_weights(
        self,
        ohlcv_map: dict[str, pd.DataFrame],
        feature_map: dict[str, pd.DataFrame] | None = None,
        benchmark_close: pd.Series | None = None,
    ) -> pd.DataFrame:
        """Return a date x symbol DataFrame of target weights in [0, 1]."""

    @staticmethod
    def _combine_signals(signals: dict[str, pd.Series]) -> pd.DataFrame:
        """Assemble per-symbol Series (each already 0/1 or continuous) into
        one wide DataFrame, aligned on the union of all dates, filled with 0
        (flat) rather than NaN so downstream sums behave predictably."""
        if not signals:
            return pd.DataFrame()
        df = pd.DataFrame(signals)
        return df.fillna(0.0)

def stateful_long_flat(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """Module-level version with a proper index (see BaseStrategy._stateful_long_flat
    for the contract). Kept as a free function since it's reused across
    several strategy modules that don't need a class instance."""
    idx = entry.index
    entry_arr = entry.fillna(False).to_numpy()
    exit_arr = exit_.reindex(idx).fillna(False).to_numpy()
    pos = 0
    out = []
    for e, x in zip(entry_arr, exit_arr):
        if pos == 0 and e:
            pos = 1
        elif pos == 1 and x:
            pos = 0
        out.append(pos)
    return pd.Series(out, index=idx, dtype=float)


def cross_sectional_select(
    score_wide: pd.DataFrame, top_pct: float, min_names: int = 1
) -> pd.DataFrame:
    """Given a date x symbol DataFrame of scores (higher = more attractive),
    return a date x symbol DataFrame of weights: 1/n_selected for names in
    the top `top_pct` fraction on that date (only among symbols with a
    non-NaN score that day), 0 elsewhere.
    """
    def _row_weights(row: pd.Series) -> pd.Series:
        valid = row.dropna()
        if valid.empty:
            return pd.Series(0.0, index=row.index)
        n_select = max(min_names, int(round(len(valid) * top_pct)))
        n_select = min(n_select, len(valid))
        threshold = valid.sort_values(ascending=False).iloc[n_select - 1]
        selected = valid[valid >= threshold]
        w = pd.Series(0.0, index=row.index)
        w.loc[selected.index] = 1.0 / len(selected)
        return w

    return score_wide.apply(_row_weights, axis=1)
