"""Checksum, Data Versioning, Audit Trail, Historical Revision Detection
(spec sections 15-21).

- `compute_checksum`: SHA-256 over a canonical, order-independent
  serialization of a record batch, so a later change to previously-fetched
  data can be detected (spec section 16).
- `VersionStore`: assigns `market_YYYY-MM-DD_vN` version tags per daily
  snapshot (spec section 17), bumping N only when the checksum for that
  (market, date) actually changed since it was last stored -- re-running
  the same day's validation twice is idempotent, not version-inflating.
- `AuditLog`: an append-only JSONL trail of every validation batch (spec
  section 15) -- one line per `AuditRecord`, never rewritten in place, so
  past results can always be reproduced/inspected later.
- `detect_historical_revision`: re-checks a window of recently-stored
  canonical data against what a fresh fetch now returns, flagging
  `HISTORICAL_DATA_REVISION` when a provider's own past values changed
  (spec sections 18-19) -- e.g. a dividend/split adjustment applied
  retroactively, or a provider correction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant.quality.models import AuditRecord, ValidationIssue

__all__ = ["compute_checksum", "DataVersion", "VersionStore", "AuditLog", "AuditRecord", "detect_historical_revision"]

_HASH_COLUMNS = ["symbol", "market", "date", "open", "high", "low", "close", "volume"]


def compute_checksum(df: pd.DataFrame) -> str:
    """Stable SHA-256 over a record batch: sorted by key columns first so
    row order (which can vary between provider calls) never changes the
    hash of otherwise-identical data."""
    if df is None or df.empty:
        return hashlib.sha256(b"").hexdigest()
    cols = [c for c in _HASH_COLUMNS if c in df.columns]
    ordered = df[cols].copy()
    ordered["date"] = pd.to_datetime(ordered["date"]).dt.strftime("%Y-%m-%d")
    ordered = ordered.sort_values(cols).reset_index(drop=True)
    payload = ordered.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class DataVersion:
    market: str
    as_of: str
    version: int
    checksum: str

    @property
    def tag(self) -> str:
        return f"{self.market}_{self.as_of}_v{self.version}"

    def to_dict(self) -> dict:
        return {"market": self.market, "as_of": self.as_of, "version": self.version,
                "checksum": self.checksum, "tag": self.tag}


class VersionStore:
    """Tiny JSON-file-backed store of the latest (market, as_of) ->
    (version, checksum). Not a database -- a personal research tool's
    daily snapshot count doesn't need one, and a flat file is trivially
    diffable in `git log` / GitHub Actions artifacts."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _key(self, market: str, as_of: str) -> str:
        return f"{market}|{as_of}"

    def get(self, market: str, as_of: str) -> DataVersion | None:
        row = self._data.get(self._key(market, as_of))
        if row is None:
            return None
        return DataVersion(market=market, as_of=as_of, version=row["version"], checksum=row["checksum"])

    def record(self, market: str, as_of: str, checksum: str) -> DataVersion:
        """Idempotent: the same checksum for the same (market, as_of) keeps
        the same version number; a changed checksum bumps it."""
        prior = self.get(market, as_of)
        if prior is not None and prior.checksum == checksum:
            return prior
        new_version = (prior.version + 1) if prior is not None else 1
        dv = DataVersion(market=market, as_of=as_of, version=new_version, checksum=checksum)
        self._data[self._key(market, as_of)] = {"version": new_version, "checksum": checksum}
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        return dv


class AuditLog:
    """Append-only JSON-Lines audit trail."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), default=str) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


def detect_historical_revision(
    stored: pd.DataFrame,
    fresh: pd.DataFrame,
    market: str,
    cfg: dict,
) -> tuple[list[ValidationIssue], int]:
    """Compare previously-stored canonical values against a fresh re-fetch
    over the trailing `lookback_sessions` window. Returns (issues, n_revised).
    A revision is WARNING, not FATAL -- providers correcting past data is
    expected behavior (dividend/split back-adjustment, vendor correction),
    not itself a data quality failure; it just must be recorded, not
    silently absorbed."""
    tol_pct = cfg["revision"]["revision_tolerance_pct"] / 100.0
    issues: list[ValidationIssue] = []

    if stored is None or stored.empty or fresh is None or fresh.empty:
        return issues, 0

    s = stored.copy()
    f = fresh.copy()
    s["date"] = pd.to_datetime(s["date"]).dt.normalize()
    f["date"] = pd.to_datetime(f["date"]).dt.normalize()

    merged = s.merge(f, on=["symbol", "date"], suffixes=("_stored", "_fresh"), how="inner")
    n_revised = 0
    for _, row in merged.iterrows():
        for field in ("open", "high", "low", "close"):
            old, new = row.get(f"{field}_stored"), row.get(f"{field}_fresh")
            if old is None or new is None or pd.isna(old) or pd.isna(new) or old == 0:
                continue
            rel_diff = abs(new - old) / abs(old)
            if rel_diff > tol_pct:
                n_revised += 1
                issues.append(ValidationIssue(
                    "historical_revision", "WARNING",
                    f"HISTORICAL_DATA_REVISION: {field} changed from {old} to {new} "
                    f"({rel_diff:.1%}) -- likely adjustment/correction by provider",
                    market, row["symbol"], str(row["date"].date()),
                ))
                break  # one flag per row is enough detail

    return issues, n_revised
