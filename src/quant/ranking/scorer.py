"""Strategy Ranking Engine (spec section 13).

Never ranks strategies by CAGR alone. Builds a composite "Quant Strategy
Score" out of several cross-sectionally normalized sub-scores (return,
risk-adjusted return, stability, out-of-sample performance, robustness) net
of penalties (drawdown, overfitting, transaction cost drag) -- weights come
from config/ranking.yaml and are meant to be tuned there, not in code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import config
from quant.ranking.overfitting import assess_overfitting
from quant.validation.walk_forward import WalkForwardResult


@dataclass
class StrategyFeatures:
    strategy_id: str
    market: str
    avg_is_cagr: float
    avg_oos_cagr: float
    avg_is_sharpe: float
    avg_oos_sharpe: float
    avg_oos_sortino: float
    avg_oos_calmar: float
    aggregate_oos_cagr: float
    aggregate_oos_sharpe: float
    aggregate_oos_mdd: float
    stability_ratio: float
    n_oos_trades: int
    n_folds: int
    avg_turnover: float
    n_param_combos_tested: int = 1


@dataclass
class StrategyScore:
    strategy_id: str
    market: str
    return_score: float
    risk_adjusted_return_score: float
    stability_score: float
    oos_score: float
    robustness_score: float
    drawdown_penalty: float
    overfitting_penalty: float
    cost_efficiency_penalty: float
    composite_score: float
    meets_minimum_requirements: bool
    overfitting_warnings: list[str] = field(default_factory=list)


def extract_features(wf: WalkForwardResult, n_param_combos_tested: int = 1) -> StrategyFeatures:
    folds = wf.fold_results
    if not folds:
        return StrategyFeatures(
            strategy_id=wf.strategy_id, market=wf.market,
            avg_is_cagr=0.0, avg_oos_cagr=0.0, avg_is_sharpe=0.0, avg_oos_sharpe=0.0,
            avg_oos_sortino=0.0, avg_oos_calmar=0.0, aggregate_oos_cagr=0.0,
            aggregate_oos_sharpe=0.0, aggregate_oos_mdd=0.0, stability_ratio=0.0,
            n_oos_trades=0, n_folds=0, avg_turnover=0.0,
        )

    def _avg(getter):
        vals = [getter(f) for f in folds]
        return float(np.nanmean(vals)) if vals else 0.0

    stable_flags = [f.stability.is_stable for f in folds if f.stability is not None]

    return StrategyFeatures(
        strategy_id=wf.strategy_id, market=wf.market,
        avg_is_cagr=_avg(lambda f: f.is_metrics.cagr),
        avg_oos_cagr=_avg(lambda f: f.oos_metrics.cagr),
        avg_is_sharpe=_avg(lambda f: f.is_metrics.sharpe),
        avg_oos_sharpe=_avg(lambda f: f.oos_metrics.sharpe),
        avg_oos_sortino=_avg(lambda f: f.oos_metrics.sortino),
        avg_oos_calmar=_avg(lambda f: f.oos_metrics.calmar),
        aggregate_oos_cagr=wf.aggregate_oos_metrics.cagr,
        aggregate_oos_sharpe=wf.aggregate_oos_metrics.sharpe,
        aggregate_oos_mdd=wf.aggregate_oos_metrics.max_drawdown,
        stability_ratio=float(np.mean(stable_flags)) if stable_flags else 0.0,
        n_oos_trades=sum(f.oos_metrics.num_trades for f in folds),
        n_folds=len(folds),
        avg_turnover=_avg(lambda f: f.oos_metrics.avg_turnover),
        n_param_combos_tested=n_param_combos_tested,
    )


def _pct_rank(series: pd.Series, ascending_is_better: bool = False) -> pd.Series:
    """Cross-sectional percentile rank in [0, 1], 1 = best.

    `ascending_is_better=False` (default): a HIGHER raw value is better
    (e.g. CAGR, Sharpe) -- the largest value gets pct rank 1.0. This needs
    pandas' own `ascending=True` (pandas: ascending=True means the largest
    value receives the highest rank/pct -- verified empirically, since this
    is easy to get backwards).
    `ascending_is_better=True`: a LOWER raw value is better (e.g. |drawdown|,
    turnover) -- the smallest value gets pct rank 1.0, which needs pandas'
    `ascending=False`.

    Constant/degenerate columns (all-equal or all-NaN) rank everyone at a
    neutral 0.5 rather than an arbitrary tie order.
    """
    if series.nunique(dropna=True) <= 1:
        return pd.Series(0.5, index=series.index)
    ranked = series.rank(pct=True, ascending=not ascending_is_better)
    return ranked.fillna(0.5)


def rank_strategies(features: list[StrategyFeatures]) -> pd.DataFrame:
    if not features:
        return pd.DataFrame()

    weights = config.ranking_config()["strategy_score_weights"]
    min_req = config.ranking_config()["minimum_requirements"]

    df = pd.DataFrame([vars(f) for f in features]).set_index("strategy_id")

    return_score = _pct_rank(df["aggregate_oos_cagr"])
    risk_adj_score = 0.5 * _pct_rank(df["avg_oos_sharpe"]) + 0.5 * _pct_rank(df["avg_oos_sortino"])
    stability_score = _pct_rank(df["stability_ratio"])
    oos_score = _pct_rank(df["aggregate_oos_sharpe"])
    robustness_score = 0.5 * _pct_rank(df["n_oos_trades"]) + 0.5 * _pct_rank(df["n_folds"])
    drawdown_penalty = _pct_rank(df["aggregate_oos_mdd"].abs(), ascending_is_better=True)  # smaller |MDD| -> higher (better) score, then used as a penalty complement below
    cost_penalty_score = _pct_rank(df["avg_turnover"], ascending_is_better=True)  # lower turnover -> higher score

    overfitting_scores = []
    warnings_by_strategy = {}
    for f in features:
        assessment = assess_overfitting(
            f.strategy_id, f.avg_is_sharpe, f.avg_oos_sharpe, f.n_oos_trades, f.n_param_combos_tested,
        )
        risk_to_penalty = {"low": 0.0, "medium": 0.5, "high": 1.0}
        overfitting_scores.append(risk_to_penalty[assessment.risk_level])
        warnings_by_strategy[f.strategy_id] = assessment.reasons
    overfitting_penalty_raw = pd.Series(overfitting_scores, index=df.index)  # 0=none, 1=severe

    # drawdown/overfitting/cost are configured as *penalty* weights (positive
    # numbers meaning "how much to subtract"), so apply them as subtractions
    composite = (
        weights["return_score"] * return_score
        + weights["risk_adjusted_return_score"] * risk_adj_score
        + weights["stability_score"] * stability_score
        + weights["oos_score"] * oos_score
        + weights["robustness_score"] * robustness_score
        - weights["drawdown_penalty"] * (1 - drawdown_penalty)
        - weights["overfitting_penalty"] * overfitting_penalty_raw
        - weights["cost_efficiency_penalty"] * (1 - cost_penalty_score)
    )

    out = pd.DataFrame({
        "market": df["market"],
        "return_score": return_score, "risk_adjusted_return_score": risk_adj_score,
        "stability_score": stability_score, "oos_score": oos_score,
        "robustness_score": robustness_score,
        "drawdown_penalty": 1 - drawdown_penalty,
        "overfitting_penalty": overfitting_penalty_raw,
        "cost_efficiency_penalty": 1 - cost_penalty_score,
        "composite_score": composite,
        "n_oos_trades": df["n_oos_trades"], "n_folds": df["n_folds"],
    })
    out["meets_minimum_requirements"] = (
        (df["n_oos_trades"] >= min_req["min_trades"]) & (df["n_folds"] >= min_req["min_oos_periods"])
    )
    out["overfitting_warnings"] = out.index.map(lambda sid: warnings_by_strategy.get(sid, []))
    out = out.sort_values("composite_score", ascending=False)
    return out
