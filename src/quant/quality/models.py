"""Shared data types for the Data Quality Engine (spec sections 3-21).

Kept in one module so `schema.py`, `ohlc.py`, `completeness.py`,
`cross_source.py`, `audit.py`, and `engine.py` all speak the same
vocabulary, and so a report can be serialized to JSON for the static
dashboard (spec section 33-34) without every module reinventing that shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Severity = Literal["INFO", "WARNING", "FATAL"]
OutlierStatus = Literal["VALID", "REVIEW", "QUARANTINED", "REJECTED"]
OverallStatus = Literal["PASS", "FAIL"]


@dataclass
class ValidationIssue:
    check: str
    severity: Severity
    message: str
    market: str | None = None
    symbol: str | None = None
    date: str | None = None  # ISO date string -- kept JSON-serializable directly

    def to_dict(self) -> dict:
        return {
            "check": self.check, "severity": self.severity, "message": self.message,
            "market": self.market, "symbol": self.symbol, "date": self.date,
        }


@dataclass
class CheckResult:
    """The outcome of one named validation check, possibly spanning many
    symbols. `mandatory=True` means this check's failure alone is enough to
    flip the whole day's `overall_status` to FAIL (spec section 14: no
    partial credit on mandatory checks)."""
    check: str
    mandatory: bool
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "check": self.check, "mandatory": self.mandatory, "passed": self.passed,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues[:200]],  # cap for report size
            "details": self.details,
        }


@dataclass
class DataQualityReport:
    market: str
    as_of: str
    generated_at: str
    checks: list[CheckResult] = field(default_factory=list)
    outlier_counts: dict[str, int] = field(default_factory=dict)
    n_symbols_checked: int = 0
    data_integrity_score: float = 0.0
    mandatory_validation_pass_rate: float = 0.0
    overall_status: OverallStatus = "FAIL"
    data_version: str | None = None
    checksum: str | None = None

    def mandatory_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.mandatory and not c.passed]

    def summary(self) -> dict:
        return {
            "market": self.market,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "n_symbols_checked": self.n_symbols_checked,
            "data_integrity_score": round(self.data_integrity_score, 4),
            "mandatory_validation_pass_rate": self.mandatory_validation_pass_rate,
            "overall_status": self.overall_status,
            "outlier_counts": self.outlier_counts,
            "data_version": self.data_version,
            "checksum": self.checksum,
            "checks": {c.check: {"passed": c.passed, "mandatory": c.mandatory, "issue_count": len(c.issues)}
                       for c in self.checks},
        }

    def to_dict(self) -> dict:
        d = self.summary()
        d["checks_detail"] = [c.to_dict() for c in self.checks]
        return d


@dataclass
class AuditRecord:
    timestamp: str
    market: str
    symbol: str | None
    source: str | None
    data_version: str | None
    checksum: str | None
    check: str
    result: str
    rule: str | None = None
    error: str | None = None
    canonical_source: str | None = None

    def to_dict(self) -> dict:
        return dict(vars(self))
