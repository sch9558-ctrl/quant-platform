"""Purged/embargoed combinatorial cross-validation and backtest statistics."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew


@dataclass(frozen=True)
class DrawdownStats:
    max_drawdown: float
    peak_index: int | None
    trough_index: int | None
    recovery_sessions: int | None


class PurgedCombinatorialCV:
    """Combinatorial Purged Cross-Validation over contiguous time groups.

    Every test split is a combination of n_test_groups contiguous groups.
    Training observations within purge_sessions before/after a test block
    and embargo_sessions after it are removed.
    """
    def __init__(
        self,
        n_groups: int = 6,
        n_test_groups: int = 2,
        purge_sessions: int = 5,
        embargo_sessions: int = 5,
    ):
        if n_groups < 3 or not 1 <= n_test_groups < n_groups:
            raise ValueError("invalid CPCV group configuration")
        self.n_groups = int(n_groups)
        self.n_test_groups = int(n_test_groups)
        self.purge_sessions = max(int(purge_sessions), 0)
        self.embargo_sessions = max(int(embargo_sessions), 0)

    def split(self, X):
        n = len(X)
        if n < self.n_groups:
            raise ValueError("not enough observations for requested groups")
        groups = [np.asarray(x, dtype=int) for x in np.array_split(np.arange(n), self.n_groups)]
        for selected in combinations(range(self.n_groups), self.n_test_groups):
            test = np.unique(np.concatenate([groups[i] for i in selected]))
            blocked = np.zeros(n, dtype=bool)
            blocked[test] = True
            for group_id in selected:
                g = groups[group_id]
                lo = max(0, int(g[0]) - self.purge_sessions)
                hi = min(n, int(g[-1]) + 1 + self.purge_sessions + self.embargo_sessions)
                blocked[lo:hi] = True
            train = np.flatnonzero(~blocked)
            if len(train):
                yield train, test

    def get_n_splits(self) -> int:
        return math.comb(self.n_groups, self.n_test_groups)


def annualized_sharpe(returns, periods_per_year: int = 252) -> float:
    r = pd.Series(returns, dtype=float).dropna()
    if len(r) < 2 or float(r.std(ddof=1)) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year))


def deflated_sharpe_ratio(
    returns,
    *,
    n_trials: int = 1,
    periods_per_year: int = 252,
) -> float:
    """Approximate Deflated Sharpe Ratio as a probability in [0, 1]."""
    r = pd.Series(returns, dtype=float).dropna()
    n = len(r)
    if n < 3:
        return 0.0
    sr_ann = annualized_sharpe(r, periods_per_year)
    sr = sr_ann / math.sqrt(periods_per_year)
    trials = max(int(n_trials), 1)
    sr_std = 1.0 / math.sqrt(max(n - 1, 1))
    if trials == 1:
        benchmark = 0.0
    else:
        gamma = 0.5772156649015329
        a = norm.ppf(max(1e-12, 1.0 - 1.0 / trials))
        b = norm.ppf(max(1e-12, 1.0 - 1.0 / (trials * math.e)))
        benchmark = sr_std * ((1.0 - gamma) * a + gamma * b)
    sk = float(skew(r, bias=False)) if n >= 3 else 0.0
    ku = float(kurtosis(r, fisher=False, bias=False)) if n >= 4 else 3.0
    denom = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * sr * sr))
    z = (sr - benchmark) * math.sqrt(n - 1) / denom
    return float(np.clip(norm.cdf(z), 0.0, 1.0))


def max_drawdown_recovery(returns) -> DrawdownStats:
    r = pd.Series(returns, dtype=float).fillna(0.0).reset_index(drop=True)
    if r.empty:
        return DrawdownStats(0.0, None, None, None)
    equity = (1.0 + r).cumprod()
    peaks = equity.cummax()
    dd = equity / peaks - 1.0
    trough = int(dd.idxmin())
    mdd = float(dd.iloc[trough])
    peak_candidates = equity.iloc[: trough + 1]
    peak_value = float(peaks.iloc[trough])
    peak_idx = int(peak_candidates[peak_candidates == peak_value].index[0])
    after = equity.iloc[trough + 1 :]
    recovered = after[after >= peak_value]
    recovery = None if recovered.empty else int(recovered.index[0] - trough)
    return DrawdownStats(mdd, peak_idx, trough, recovery)


def calmar_ratio(returns, periods_per_year: int = 252) -> float:
    r = pd.Series(returns, dtype=float).dropna()
    if r.empty:
        return 0.0
    years = max(len(r) / periods_per_year, 1.0 / periods_per_year)
    total = float((1.0 + r).prod())
    cagr = total ** (1.0 / years) - 1.0 if total > 0 else -1.0
    mdd = abs(max_drawdown_recovery(r).max_drawdown)
    return float(cagr / mdd) if mdd > 0 else float("inf") if cagr > 0 else 0.0


def profit_factor(returns) -> float:
    r = pd.Series(returns, dtype=float).dropna()
    gains = float(r[r > 0].sum())
    losses = abs(float(r[r < 0].sum()))
    return float(gains / losses) if losses > 0 else float("inf") if gains > 0 else 0.0
