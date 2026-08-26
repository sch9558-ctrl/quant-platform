"""Parameter Stability / Robustness analysis (spec section 8).

The whole point of this module: do NOT pick the single best-performing
parameter combination from a grid search. A combination that is great in
isolation but surrounded by poor neighbors (MA=49 is great, 48 and 50 are
terrible) is almost certainly overfit noise. Instead, score every candidate
by how well its *neighborhood* of nearby parameter values performs on
average, and prefer broad, stable plateaus.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from quant import config


@dataclass
class ParamEvalResult:
    params: dict
    score: float
    extra: dict


@dataclass
class StabilityResult:
    params: dict
    own_score: float
    neighbor_avg_score: float
    neighbor_count: int
    degradation_pct: float | None  # (own - neighbor_avg) / |own|, None if own_score == 0
    is_stable: bool


def evaluate_param_grid(
    param_grid: dict[str, list],
    eval_fn: Callable[[dict], float],
    extra_fn: Callable[[dict], dict] | None = None,
) -> list[ParamEvalResult]:
    """Evaluate every combination in `param_grid` (a dict of param_name ->
    list of candidate values) via `eval_fn(params) -> scalar score` (e.g.
    in-sample Sharpe). Grids in config/strategies.yaml are small (a few
    dozen combinations at most), so a full grid search is cheap enough not
    to need anything smarter for a personal research tool.
    """
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        score = eval_fn(params)
        extra = extra_fn(params) if extra_fn else {}
        results.append(ParamEvalResult(params=params, score=score, extra=extra))
    return results


def _is_neighbor(a: dict, b: dict, perturbation_pct: float) -> bool:
    if a == b:
        return False
    for key in a:
        va, vb = a[key], b[key]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if va == 0:
                if vb != 0:
                    return False
                continue
            if abs(vb - va) / abs(va) > perturbation_pct:
                return False
        else:
            if va != vb:
                return False
    return True


def neighborhood_stability(
    results: list[ParamEvalResult],
    perturbation_pct: float | None = None,
    max_degradation_pct: float | None = None,
) -> list[StabilityResult]:
    cfg = config.validation_config()["parameter_stability"]
    perturbation_pct = perturbation_pct if perturbation_pct is not None else cfg["perturbation_pct"]
    max_degradation_pct = max_degradation_pct if max_degradation_pct is not None else cfg["max_metric_degradation_pct"]

    out = []
    for r in results:
        neighbors = [o for o in results if _is_neighbor(r.params, o.params, perturbation_pct)]
        if neighbors:
            neighbor_avg = sum(n.score for n in neighbors) / len(neighbors)
        else:
            neighbor_avg = r.score  # no neighbors in grid -> can't judge, assume neutral

        if r.score == 0 or math.isnan(r.score):
            degradation = None
            is_stable = False
        else:
            degradation = (r.score - neighbor_avg) / abs(r.score)
            is_stable = len(neighbors) > 0 and degradation <= max_degradation_pct

        out.append(StabilityResult(
            params=r.params, own_score=r.score, neighbor_avg_score=neighbor_avg,
            neighbor_count=len(neighbors), degradation_pct=degradation, is_stable=is_stable,
        ))
    return out


def select_robust_params(
    results: list[ParamEvalResult],
    perturbation_pct: float | None = None,
    max_degradation_pct: float | None = None,
    min_neighbors: int = 1,
) -> StabilityResult | None:
    """Choose the params with the best *neighborhood-average* score among
    candidates that have enough neighbors to judge and aren't isolated
    spikes -- not simply the single highest-scoring combination.
    """
    stability = neighborhood_stability(results, perturbation_pct, max_degradation_pct)
    candidates = [s for s in stability if s.neighbor_count >= min_neighbors and s.is_stable]
    if not candidates:
        # nothing passes the stability bar; fall back to the best
        # neighborhood-average among everything (better than nothing, but
        # callers should treat this as a robustness warning -- see
        # ranking/overfitting.py)
        candidates = stability
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.neighbor_avg_score)


def stability_frame(results: list[ParamEvalResult]) -> pd.DataFrame:
    stability = neighborhood_stability(results)
    rows = []
    for s in stability:
        row = dict(s.params)
        row.update({
            "own_score": s.own_score, "neighbor_avg_score": s.neighbor_avg_score,
            "neighbor_count": s.neighbor_count, "degradation_pct": s.degradation_pct,
            "is_stable": s.is_stable,
        })
        rows.append(row)
    return pd.DataFrame(rows)
