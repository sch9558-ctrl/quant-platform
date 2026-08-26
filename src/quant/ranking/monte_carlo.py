"""Monte Carlo Analysis (spec section 15).

Bootstraps a strategy's own historical return sequence (daily returns or
round-trip trade returns) to build a distribution of *possible* outcomes,
instead of trusting the one specific historical path that happened to occur.
Supports an optional block bootstrap (`block_size > 1`) to partially
preserve serial correlation in the resampled sequence.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    n_simulations: int
    horizon: int
    median_final_return: float
    mean_final_return: float
    worst_case_final_return: float     # 5th percentile
    best_case_final_return: float       # 95th percentile
    median_max_drawdown: float
    drawdown_95th_percentile: float     # "95% of simulated paths had a max drawdown shallower than this"
    risk_of_ruin: float                 # fraction of paths breaching `ruin_threshold`
    final_return_distribution: np.ndarray
    max_drawdown_distribution: np.ndarray


def _block_bootstrap_sample(returns: np.ndarray, horizon: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    if block_size <= 1:
        idx = rng.integers(0, len(returns), size=horizon)
        return returns[idx]

    n_blocks = int(np.ceil(horizon / block_size))
    max_start = len(returns) - block_size
    if max_start < 0:
        idx = rng.integers(0, len(returns), size=horizon)
        return returns[idx]

    chunks = []
    for _ in range(n_blocks):
        start = rng.integers(0, max_start + 1)
        chunks.append(returns[start:start + block_size])
    return np.concatenate(chunks)[:horizon]


def run_monte_carlo(
    returns: pd.Series | np.ndarray,
    n_simulations: int = 2000,
    horizon: int | None = None,
    block_size: int = 5,
    ruin_threshold: float = -0.5,
    seed: int | None = None,
) -> MonteCarloResult:
    arr = np.asarray(returns.dropna() if isinstance(returns, pd.Series) else returns, dtype=float)
    if len(arr) == 0:
        empty = np.array([])
        return MonteCarloResult(
            n_simulations=0, horizon=0, median_final_return=0.0, mean_final_return=0.0,
            worst_case_final_return=0.0, best_case_final_return=0.0, median_max_drawdown=0.0,
            drawdown_95th_percentile=0.0, risk_of_ruin=0.0,
            final_return_distribution=empty, max_drawdown_distribution=empty,
        )

    horizon = horizon or len(arr)
    rng = np.random.default_rng(seed)

    final_returns = np.empty(n_simulations)
    max_dds = np.empty(n_simulations)
    ruin_count = 0

    for i in range(n_simulations):
        sampled = _block_bootstrap_sample(arr, horizon, block_size, rng)
        equity = np.cumprod(1 + sampled)
        final_returns[i] = equity[-1] - 1
        running_max = np.maximum.accumulate(equity)
        dd = equity / running_max - 1
        min_dd = dd.min()
        max_dds[i] = min_dd
        if min_dd <= ruin_threshold:
            ruin_count += 1

    return MonteCarloResult(
        n_simulations=n_simulations, horizon=horizon,
        median_final_return=float(np.median(final_returns)),
        mean_final_return=float(np.mean(final_returns)),
        worst_case_final_return=float(np.percentile(final_returns, 5)),
        best_case_final_return=float(np.percentile(final_returns, 95)),
        median_max_drawdown=float(np.median(max_dds)),
        drawdown_95th_percentile=float(np.percentile(max_dds, 5)),
        risk_of_ruin=ruin_count / n_simulations,
        final_return_distribution=final_returns,
        max_drawdown_distribution=max_dds,
    )
