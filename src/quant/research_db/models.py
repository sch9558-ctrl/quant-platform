"""Research DB record schema (spec sections 19 and 30: reproducibility)."""
from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field

import pandas as pd

from quant import config


@dataclass
class ExperimentRecord:
    experiment_id: str
    created_at: pd.Timestamp
    market: str
    strategy_id: str
    params: dict
    universe_description: str
    backtest_start: str
    backtest_end: str
    is_metrics: dict
    oos_metrics: dict
    aggregate_oos_metrics: dict
    cost_config: dict
    code_version: str | None
    dataset_version: str
    composite_score: float | None = None
    overfitting_risk: str | None = None
    notes: str = ""

    def to_row(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at.isoformat(),
            "market": self.market,
            "strategy_id": self.strategy_id,
            "params_json": json.dumps(self.params),
            "universe_description": self.universe_description,
            "backtest_start": self.backtest_start,
            "backtest_end": self.backtest_end,
            "is_metrics_json": json.dumps(self.is_metrics, default=str),
            "oos_metrics_json": json.dumps(self.oos_metrics, default=str),
            "aggregate_oos_metrics_json": json.dumps(self.aggregate_oos_metrics, default=str),
            "cost_config_json": json.dumps(self.cost_config),
            "code_version": self.code_version,
            "dataset_version": self.dataset_version,
            "composite_score": self.composite_score,
            "overfitting_risk": self.overfitting_risk,
            "notes": self.notes,
        }

    @classmethod
    def from_row(cls, row: dict) -> "ExperimentRecord":
        return cls(
            experiment_id=row["experiment_id"],
            created_at=pd.Timestamp(row["created_at"]),
            market=row["market"], strategy_id=row["strategy_id"],
            params=json.loads(row["params_json"]),
            universe_description=row["universe_description"],
            backtest_start=row["backtest_start"], backtest_end=row["backtest_end"],
            is_metrics=json.loads(row["is_metrics_json"]),
            oos_metrics=json.loads(row["oos_metrics_json"]),
            aggregate_oos_metrics=json.loads(row["aggregate_oos_metrics_json"]),
            cost_config=json.loads(row["cost_config_json"]),
            code_version=row["code_version"], dataset_version=row["dataset_version"],
            composite_score=row["composite_score"], overfitting_risk=row["overfitting_risk"],
            notes=row["notes"] or "",
        )


def new_experiment_id() -> str:
    return uuid.uuid4().hex[:16]


def current_code_version() -> str | None:
    """Git commit hash of the working tree, if this is a git repo with git
    available -- best-effort, returns None otherwise rather than raising
    (a personal research tool shouldn't fail an experiment save just
    because git isn't on PATH)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=config.REPO_ROOT,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def dataset_version_tag(market: str, symbols: list[str], start: str, end: str) -> str:
    """Best-effort dataset version tag: NOT a cryptographic content hash of
    the actual price data (this platform doesn't yet snapshot raw data
    files with content hashes -- see ARCHITECTURE.md future expansion), but
    a reproducible fingerprint of *which* data was requested (market,
    universe membership, date range) so a later run with the same tag was
    at least asking for the same inputs. Swap in a true content hash (e.g.
    over the cached parquet files) if bit-for-bit reproducibility is needed.
    """
    import hashlib
    payload = f"{market}|{sorted(symbols)}|{start}|{end}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class PointInTimeObservation:
    """One externally observed fact with an explicit publication timestamp.

    published_at is the causality gate: historical queries may only see
    observations whose publication time was known by the requested as-of.
    collected_at is provenance only and records when this platform fetched
    the observation. effective_at may be in the future (for example a known
    earnings date) and is therefore deliberately not used as the as-of gate.
    """
    observation_id: str
    observation_type: str
    source: str
    market: str
    symbol: str | None
    published_at: pd.Timestamp
    collected_at: pd.Timestamp
    effective_at: pd.Timestamp | None
    payload: dict
    provenance: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "observation_type": self.observation_type,
            "source": self.source,
            "market": self.market,
            "symbol": self.symbol,
            "published_at": self.published_at.isoformat(),
            "collected_at": self.collected_at.isoformat(),
            "effective_at": self.effective_at.isoformat() if self.effective_at is not None else None,
            "payload_json": json.dumps(self.payload, default=str),
            "provenance_json": json.dumps(self.provenance, default=str),
        }

    @classmethod
    def from_row(cls, row: dict) -> "PointInTimeObservation":
        return cls(
            observation_id=row["observation_id"],
            observation_type=row["observation_type"],
            source=row["source"],
            market=row["market"],
            symbol=row["symbol"],
            published_at=pd.Timestamp(row["published_at"]),
            collected_at=pd.Timestamp(row["collected_at"]),
            effective_at=pd.Timestamp(row["effective_at"]) if row["effective_at"] else None,
            payload=json.loads(row["payload_json"]),
            provenance=json.loads(row["provenance_json"] or "{}"),
        )


def new_observation_id() -> str:
    return uuid.uuid4().hex[:20]
