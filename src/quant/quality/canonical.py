"""Canonical Data Layer (spec section 11).

Builds the single "Canonical Data" table the rest of the pipeline is
allowed to use, from a Primary source plus (optionally) a Secondary source
that has already been compared via `cross_source.compare_sources`.

Deliberately NOT a plain average of sources (spec: "단순 평균을 내지
않는다"): the Primary source wins whenever it agrees with the Secondary
within tolerance, or whenever no Secondary value exists for that row at
all. A row that disagrees beyond tolerance is EXCLUDED from the canonical
table entirely rather than guessed at -- spec section 10:
"해당 데이터는 자동으로 전략에 사용하지 않는다" -- and every row keeps a
`ProvenanceRecord` explaining exactly why it was included or excluded, so a
later reviewer (or the audit trail) can see the reasoning, not just the
result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

_COMPARE_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class ProvenanceRecord:
    symbol: str
    date: str
    primary_source: str | None
    secondary_source: str | None
    primary_values: dict = field(default_factory=dict)
    secondary_values: dict | None = None
    difference_pct: float | None = None
    validation: str = "PASS"          # PASS | SOURCE_MISMATCH | SECONDARY_UNAVAILABLE
    canonical_source: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return dict(vars(self))


def build_canonical(
    primary: pd.DataFrame,
    secondary: pd.DataFrame | None,
    comparison: pd.DataFrame | None,
    primary_source_name: str,
    secondary_source_name: str | None,
) -> tuple[pd.DataFrame, list[ProvenanceRecord]]:
    """Returns (canonical_long_records, provenance). `canonical_long_records`
    has the same long-record shape as `primary` but with mismatched
    (symbol, date) rows removed."""
    if primary is None or primary.empty:
        return primary if primary is not None else pd.DataFrame(), []

    primary = primary.copy()
    primary["date"] = pd.to_datetime(primary["date"]).dt.normalize()

    mismatch_keys: set[tuple] = set()
    mismatch_lookup: dict[tuple, float] = {}
    if comparison is not None and not comparison.empty:
        mismatched = comparison[comparison["mismatch"]]
        for _, row in mismatched.iterrows():
            key = (row["symbol"], pd.Timestamp(row["date"]).normalize())
            mismatch_keys.add(key)
            mismatch_lookup[key] = float(row["max_relative_diff"])

    secondary_index = None
    if secondary is not None and not secondary.empty:
        sec = secondary.copy()
        sec["date"] = pd.to_datetime(sec["date"]).dt.normalize()
        secondary_index = sec.set_index(["symbol", "date"])

    provenance: list[ProvenanceRecord] = []
    keep_mask = []

    for _, row in primary.iterrows():
        key = (row["symbol"], row["date"])
        primary_vals = {c: row[c] for c in _COMPARE_COLUMNS if c in primary.columns}

        if key in mismatch_keys:
            keep_mask.append(False)
            sec_vals = None
            if secondary_index is not None and key in secondary_index.index:
                sec_row = secondary_index.loc[key]
                sec_vals = {c: sec_row[c] for c in _COMPARE_COLUMNS if c in secondary.columns}
            provenance.append(ProvenanceRecord(
                symbol=key[0], date=str(key[1].date()),
                primary_source=primary_source_name, secondary_source=secondary_source_name,
                primary_values=primary_vals, secondary_values=sec_vals,
                difference_pct=mismatch_lookup.get(key), validation="SOURCE_MISMATCH",
                canonical_source=None,
                reason="Primary and secondary values disagree beyond tolerance -- excluded, not averaged or guessed at.",
            ))
            continue

        keep_mask.append(True)
        sec_vals = None
        validation = "SECONDARY_UNAVAILABLE"
        reason = "No secondary-source value available for this row; primary used as-is."
        if secondary_index is not None and key in secondary_index.index:
            sec_row = secondary_index.loc[key]
            sec_vals = {c: sec_row[c] for c in _COMPARE_COLUMNS if c in secondary.columns}
            validation = "PASS"
            reason = "Primary and secondary values agree within tolerance."

        provenance.append(ProvenanceRecord(
            symbol=key[0], date=str(key[1].date()),
            primary_source=primary_source_name, secondary_source=secondary_source_name,
            primary_values=primary_vals, secondary_values=sec_vals,
            difference_pct=None, validation=validation,
            canonical_source=primary_source_name, reason=reason,
        ))

    canonical = primary.loc[keep_mask].reset_index(drop=True)
    return canonical, provenance
