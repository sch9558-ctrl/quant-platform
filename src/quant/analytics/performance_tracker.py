"""Prediction snapshot logging and post-mortem evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import uuid

import pandas as pd


@dataclass
class PredictionSnapshot:
    prediction_id: str
    market: str
    symbol: str
    generated_at: str
    entry_price: float
    target_price: float
    stop_price: float
    expiry_date: str
    analyst_id: str | None = None
    analyst_bias: float | None = None
    regime_factor: float | None = None
    alpha: float | None = None
    outcome: str = "OPEN"
    resolved_at: str | None = None
    realized_return: float | None = None
    realized_risk_reward: float | None = None
    mfe: float | None = None
    mae: float | None = None


class PerformanceTracker:
    def __init__(self, path: str | Path = "data/db/predictions_log.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **kwargs) -> PredictionSnapshot:
        snap = PredictionSnapshot(
            prediction_id=kwargs.pop("prediction_id", uuid.uuid4().hex),
            generated_at=kwargs.pop("generated_at", pd.Timestamp.now(tz="UTC").isoformat()),
            **kwargs,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(snap), ensure_ascii=False) + "\n")
        return snap

    def load(self) -> list[PredictionSnapshot]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(PredictionSnapshot(**json.loads(line)))
        return out

    @staticmethod
    def evaluate(snapshot: PredictionSnapshot, price_df: pd.DataFrame) -> PredictionSnapshot:
        if price_df is None or price_df.empty:
            return snapshot
        df = price_df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "date" not in df:
                return snapshot
            df.index = pd.to_datetime(df["date"])
        start = pd.Timestamp(snapshot.generated_at).tz_localize(None).normalize()
        end = pd.Timestamp(snapshot.expiry_date).tz_localize(None).normalize()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        w = df.loc[(df.index >= start) & (df.index <= end)].copy()
        if w.empty:
            return snapshot

        high = pd.to_numeric(w.get("high", w["close"]), errors="coerce")
        low = pd.to_numeric(w.get("low", w["close"]), errors="coerce")
        snapshot.mfe = float(high.max() / snapshot.entry_price - 1)
        snapshot.mae = float(low.min() / snapshot.entry_price - 1)

        target_hits = w.index[high >= snapshot.target_price]
        stop_hits = w.index[low <= snapshot.stop_price]
        first_target = target_hits.min() if len(target_hits) else None
        first_stop = stop_hits.min() if len(stop_hits) else None

        if first_target is not None and (first_stop is None or first_target <= first_stop):
            exit_price, outcome, resolved = snapshot.target_price, "TARGET_REACHED", first_target
        elif first_stop is not None:
            exit_price, outcome, resolved = snapshot.stop_price, "STOPPED_OUT", first_stop
        elif w.index.max() >= end:
            exit_price = float(pd.to_numeric(w["close"], errors="coerce").dropna().iloc[-1])
            outcome, resolved = "EXPIRED", w.index.max()
        else:
            return snapshot

        risk = max(snapshot.entry_price - snapshot.stop_price, 1e-9)
        reward = exit_price - snapshot.entry_price
        snapshot.outcome = outcome
        snapshot.resolved_at = pd.Timestamp(resolved).isoformat()
        snapshot.realized_return = float(exit_price / snapshot.entry_price - 1)
        snapshot.realized_risk_reward = float(reward / risk)
        return snapshot

    def rewrite(self, rows: list[PredictionSnapshot]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
