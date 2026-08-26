"""Train / Validation / Out-of-Sample splitting (spec section 10).

Prefers rolling Walk-Forward folds (repeatedly: N years train -> 1 year
validation -> 1 year out-of-sample, then roll forward) whenever there is
enough history; falls back to one fixed IS/Val/OOS split (by percentage of
the available date range) for shorter histories, per config/validation.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant import config


@dataclass
class Fold:
    fold_id: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp

    def as_dict(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "is_start": self.is_start, "is_end": self.is_end,
            "val_start": self.val_start, "val_end": self.val_end,
            "oos_start": self.oos_start, "oos_end": self.oos_end,
        }


def generate_walk_forward_folds(start: str, end: str, cfg: dict | None = None) -> list[Fold]:
    cfg = cfg or config.validation_config()["split"]
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    is_years, val_years, oos_years, step_years = (
        cfg["in_sample_years"], cfg["validation_years"], cfg["out_of_sample_years"], cfg["step_years"],
    )

    folds: list[Fold] = []
    cur_is_start = start_ts
    fold_id = 0
    while True:
        is_end = cur_is_start + pd.DateOffset(years=is_years) - pd.Timedelta(days=1)
        val_start = is_end + pd.Timedelta(days=1)
        val_end = val_start + pd.DateOffset(years=val_years) - pd.Timedelta(days=1)
        oos_start = val_end + pd.Timedelta(days=1)
        oos_end = oos_start + pd.DateOffset(years=oos_years) - pd.Timedelta(days=1)

        if oos_end > end_ts:
            break

        folds.append(Fold(fold_id, cur_is_start, is_end, val_start, val_end, oos_start, min(oos_end, end_ts)))
        fold_id += 1
        cur_is_start = cur_is_start + pd.DateOffset(years=step_years)

    return folds


def fixed_split(start: str, end: str, cfg: dict | None = None) -> Fold:
    cfg = cfg or config.validation_config()["fixed_split_fallback"]
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    total_days = (end_ts - start_ts).days
    is_end = start_ts + pd.Timedelta(days=int(total_days * cfg["in_sample_pct"]))
    val_end = is_end + pd.Timedelta(days=int(total_days * cfg["validation_pct"]))
    return Fold(
        fold_id=0, is_start=start_ts, is_end=is_end,
        val_start=is_end + pd.Timedelta(days=1), val_end=val_end,
        oos_start=val_end + pd.Timedelta(days=1), oos_end=end_ts,
    )


def get_folds(start: str, end: str) -> list[Fold]:
    """Return walk-forward folds if there's enough history for
    config/validation.yaml's minimum, otherwise a single fixed split."""
    val_cfg = config.validation_config()["split"]
    total_years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25

    if val_cfg["method"] == "walk_forward" and total_years >= val_cfg["min_total_years"]:
        folds = generate_walk_forward_folds(start, end, val_cfg)
        if folds:
            return folds

    return [fixed_split(start, end)]
