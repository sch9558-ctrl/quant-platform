"""Walk-forward adaptive calibration parameters."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdaptiveState:
    alpha: float
    analyst_weight: float
    rmse: float | None
    n_obs: int


class AdaptiveOptimizer:
    def __init__(self, lookback_months: int = 6, ema_smoothing: float = 0.25):
        self.lookback_months = int(lookback_months)
        self.ema_smoothing = float(ema_smoothing)

    def recent_frame(self, rows) -> pd.DataFrame:
        df = pd.DataFrame([r.__dict__ if hasattr(r, "__dict__") else dict(r) for r in rows])
        if df.empty:
            return df
        ts = pd.to_datetime(df["generated_at"], utc=True, errors="coerce")
        cutoff = ts.max() - pd.DateOffset(months=self.lookback_months)
        return df.loc[ts >= cutoff].copy()

    def analyst_weight(self, rows, analyst_id: str | None) -> float:
        df = self.recent_frame(rows)
        if df.empty:
            return 0.5
        if analyst_id and "analyst_id" in df:
            df = df[df["analyst_id"].fillna("") == analyst_id]
        resolved = df[df["outcome"].isin(["TARGET_REACHED","STOPPED_OUT","EXPIRED"])]
        if resolved.empty:
            return 0.5
        hit = float((resolved["outcome"] == "TARGET_REACHED").mean())
        # shrink small samples toward neutral 0.5
        confidence = min(len(resolved) / 20.0, 1.0)
        return float(np.clip(0.5 + (hit - 0.5) * confidence * 2.0, 0.0, 1.0))

    def optimize_alpha(self, rows, previous_alpha: float = 0.0, grid=None) -> AdaptiveState:
        df = self.recent_frame(rows)
        if df.empty:
            return AdaptiveState(float(previous_alpha), 0.5, None, 0)
        needed = {"entry_price","target_price","mfe"}
        if not needed.issubset(df.columns):
            return AdaptiveState(float(previous_alpha), 0.5, None, 0)
        work = df.dropna(subset=["entry_price","target_price","mfe"]).copy()
        if work.empty:
            return AdaptiveState(float(previous_alpha), 0.5, None, 0)

        realized_peak = work["entry_price"].astype(float) * (1 + work["mfe"].astype(float))
        raw_target = work["target_price"].astype(float)
        candidates = np.asarray(list(grid) if grid is not None else np.linspace(0.0, 0.5, 51), dtype=float)
        scores = []
        for alpha in candidates:
            pred = raw_target * (1.0 - alpha)
            rmse = float(np.sqrt(np.mean(np.square(pred - realized_peak))))
            scores.append((rmse, float(alpha)))
        rmse, best = min(scores, key=lambda x: x[0])
        beta = float(np.clip(self.ema_smoothing, 0.0, 1.0))
        smoothed = (1-beta)*float(previous_alpha) + beta*best
        return AdaptiveState(
            alpha=float(np.clip(smoothed, 0.0, 0.75)),
            analyst_weight=self.analyst_weight(work.to_dict("records"), None),
            rmse=rmse,
            n_obs=len(work),
        )
