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
from quant.validation.cpcv import PurgedCombinatorialCV, annualized_sharpe, deflated_sharpe_ratio


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
    deflated_sharpe_probability: float | None = None
    cpcv_positive_sharpe_ratio: float | None = None


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
            n_param_combos_tested=max(1, n_param_combos_tested),
            deflated_sharpe_probability=None,
            cpcv_positive_sharpe_ratio=None,
        )

    def _avg(getter):
        vals = [getter(f) for f in folds]
        return float(np.nanmean(vals)) if vals else 0.0

    stable_flags = [f.stability.is_stable for f in folds if f.stability is not None]

    trial_sharpes = list(getattr(wf, "parameter_trial_sharpes", ()) or ())
    inferred_trials = max(1, len(trial_sharpes), int(n_param_combos_tested or 1))
    dsr_probability = None
    cpcv_positive_ratio = None
    if wf.aggregate_oos_equity is not None and len(wf.aggregate_oos_equity) >= 4:
        oos_returns = wf.aggregate_oos_equity.pct_change().dropna()
        if len(oos_returns) >= 3:
            dsr_probability = deflated_sharpe_ratio(
                oos_returns,
                n_trials=inferred_trials,
                trial_sharpes=trial_sharpes or None,
            )
        if len(oos_returns) >= 60:
            splitter = PurgedCombinatorialCV(
                n_groups=6, n_test_groups=2, purge_sessions=2, embargo_sessions=3
            )
            split_passes = []
            values = oos_returns.reset_index(drop=True)
            for train_idx, test_idx in splitter.split(values):
                train_sharpe = annualized_sharpe(values.iloc[train_idx])
                test_sharpe = annualized_sharpe(values.iloc[test_idx])
                # Both the purged/embargoed training sample and the held-out
                # test combination must retain a positive risk-adjusted edge.
                # This makes purge/embargo affect the diagnostic rather than
                # merely generating decorative train indices.
                split_passes.append(train_sharpe > 0 and test_sharpe > 0)
            if split_passes:
                cpcv_positive_ratio = float(sum(split_passes) / len(split_passes))

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
        n_param_combos_tested=inferred_trials,
        deflated_sharpe_probability=dsr_probability,
        cpcv_positive_sharpe_ratio=cpcv_positive_ratio,
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
        "deflated_sharpe_probability": df["deflated_sharpe_probability"],
        "cpcv_positive_sharpe_ratio": df["cpcv_positive_sharpe_ratio"],
        "n_param_combos_tested": df["n_param_combos_tested"],
    })
    dsr_threshold = float(min_req.get("min_deflated_sharpe_probability", 0.5))
    dsr_ok = df["deflated_sharpe_probability"].isna() | (
        df["deflated_sharpe_probability"] >= dsr_threshold
    )
    cpcv_threshold = float(min_req.get("min_cpcv_positive_sharpe_ratio", 0.5))
    cpcv_ok = df["cpcv_positive_sharpe_ratio"].isna() | (
        df["cpcv_positive_sharpe_ratio"] >= cpcv_threshold
    )
    out["meets_minimum_requirements"] = (
        (df["n_oos_trades"] >= min_req["min_trades"])
        & (df["n_folds"] >= min_req["min_oos_periods"])
        & dsr_ok
        & cpcv_ok
    )
    out["overfitting_warnings"] = out.index.map(lambda sid: warnings_by_strategy.get(sid, []))
    out = out.sort_values("composite_score", ascending=False)
    return out
