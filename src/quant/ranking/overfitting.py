"""Overfitting Detection (spec section 14).

Flags strategies whose backtest looks good but has telltale signs of not
generalizing: a large IS/OOS performance gap, too few trades to trust the
statistics, or an OOS Sharpe that collapsed relative to IS.

Also includes a Deflated Sharpe Ratio implementation (Bailey & Lopez de
Prado, 2014) and a simplified Probability-of-Backtest-Overfitting proxy, as
extensible starting points for the more rigorous versions the spec allows
for future expansion (full combinatorially-symmetric cross-validation PBO,
proper multiple-testing correction across the whole strategy universe).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm

from quant import config

_EULER_GAMMA = 0.5772156649015329


@dataclass
class OverfittingAssessment:
    strategy_id: str
    is_sharpe: float
    oos_sharpe: float
    sharpe_gap: float
    oos_is_ratio: float | None
    n_trades: int
    n_param_combos_tested: int
    reasons: list[str] = field(default_factory=list)
    risk_level: str = "low"  # "low" | "medium" | "high"


def assess_overfitting(
    strategy_id: str,
    is_sharpe: float,
    oos_sharpe: float,
    n_trades: int,
    n_param_combos_tested: int = 1,
) -> OverfittingAssessment:
    cfg = config.ranking_config()["overfitting_thresholds"]
    reasons: list[str] = []

    gap = is_sharpe - oos_sharpe
    ratio = (oos_sharpe / is_sharpe) if is_sharpe != 0 else None

    if gap > cfg["max_is_oos_sharpe_ratio_gap"]:
        reasons.append(f"large IS/OOS Sharpe gap ({gap:.2f} > {cfg['max_is_oos_sharpe_ratio_gap']})")
    if ratio is not None and ratio < cfg["min_oos_is_sharpe_ratio"]:
        reasons.append(f"OOS Sharpe is only {ratio:.0%} of IS Sharpe (threshold {cfg['min_oos_is_sharpe_ratio']:.0%})")
    if n_trades < cfg["min_trades_for_confidence"]:
        reasons.append(f"insufficient trades for statistical confidence ({n_trades} < {cfg['min_trades_for_confidence']})")
    if n_param_combos_tested > 20:
        reasons.append(
            f"large parameter search ({n_param_combos_tested} combinations tested) -- "
            "increases the chance the chosen params are curve-fit to this specific sample; "
            "consider a stricter stability filter or a formal multiple-testing correction"
        )

    risk_level = "high" if len(reasons) >= 2 else ("medium" if len(reasons) == 1 else "low")

    return OverfittingAssessment(
        strategy_id=strategy_id, is_sharpe=is_sharpe, oos_sharpe=oos_sharpe,
        sharpe_gap=gap, oos_is_ratio=ratio, n_trades=n_trades,
        n_param_combos_tested=n_param_combos_tested, reasons=reasons, risk_level=risk_level,
    )


def deflated_sharpe_ratio(
    observed_sharpe: float,
    sharpe_std_across_trials: float,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probability the observed (per-period, non-annualized) Sharpe ratio is
    genuinely positive after accounting for selection bias from testing
    `n_trials` parameter combinations (Bailey & Lopez de Prado, 2014,
    "The Deflated Sharpe Ratio"). Returns a probability in [0, 1]; values
    well below ~0.95 suggest the backtest's apparent edge could plausibly be
    an artifact of how many combinations were tried.
    """
    if n_trials <= 1 or sharpe_std_across_trials <= 0:
        expected_max_sharpe = 0.0
    else:
        z1 = norm.ppf(1 - 1.0 / n_trials)
        z2 = norm.ppf(1 - 1.0 / (n_trials * np.e))
        expected_max_sharpe = sharpe_std_across_trials * ((1 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)

    if n_obs <= 1:
        return 0.5

    variance_term = 1 - skew * observed_sharpe + ((kurtosis - 1) / 4) * observed_sharpe ** 2
    if variance_term <= 0:
        return 0.5
    sr_std = np.sqrt(variance_term / (n_obs - 1))
    if sr_std <= 0:
        return 0.5

    return float(norm.cdf((observed_sharpe - expected_max_sharpe) / sr_std))


def probability_of_backtest_overfitting_proxy(oos_sharpes_by_trial: list[float]) -> float:
    """Simplified proxy for Probability of Backtest Overfitting: the
    fraction of tested parameter combinations whose out-of-sample Sharpe
    ratio was non-positive. This is NOT the full combinatorially-symmetric
    cross-validation (CSCV) procedure from Bailey et al. (2015) -- it's a
    cheap, directionally-correct stand-in, kept here as an explicit
    extension point (spec section 14: "가능하면 확장 가능하게 설계").
    """
    if not oos_sharpes_by_trial:
        return 0.0
    arr = np.array(oos_sharpes_by_trial)
    return float((arr <= 0).mean())
