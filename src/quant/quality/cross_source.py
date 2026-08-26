"""Multi-Source Cross Validation + Consensus (spec sections 9-11).

Compares the same (symbol, date) across a Primary and Secondary provider's
long-record tables. A value pair that disagrees beyond tolerance is marked
`SOURCE_MISMATCH` and excluded from the canonical output by
`quality.canonical.build_canonical` -- this module only compares and
reports, it does not decide the canonical value (kept separate so the
comparison logic can be unit-tested against fixed tolerance bands
independent of the consensus/priority rules).

Tolerance is deliberately wider around known corporate-action dates
(`corporate_action_grace_days`): two providers legitimately disagree on a
raw close price for a few days around a split or ex-dividend date purely
because they update their adjustment factors on different schedules --
that is not a data error and should not be reported as one.
"""
from __future__ import annotations

import pandas as pd

from quant.quality.models import CheckResult, ValidationIssue

_COMPARE_COLUMNS = ["open", "high", "low", "close"]


def compare_sources(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    cfg: dict,
    corporate_action_dates: dict[str, set] | None = None,
) -> pd.DataFrame:
    """Row-per-(symbol,date) comparison table with a `mismatch` boolean and
    per-field relative differences. Empty if either side is empty."""
    corporate_action_dates = corporate_action_dates or {}
    if primary is None or primary.empty or secondary is None or secondary.empty:
        return pd.DataFrame()

    tol = cfg["cross_source"]["tolerance"]
    grace_days = cfg["cross_source"]["corporate_action_grace_days"]

    p = primary[["symbol", "date"] + _COMPARE_COLUMNS + ["volume"]].copy()
    s = secondary[["symbol", "date"] + _COMPARE_COLUMNS + ["volume"]].copy()
    p["date"] = pd.to_datetime(p["date"]).dt.normalize()
    s["date"] = pd.to_datetime(s["date"]).dt.normalize()

    merged = p.merge(s, on=["symbol", "date"], suffixes=("_primary", "_secondary"), how="inner")
    if merged.empty:
        return merged

    rows = []
    for _, row in merged.iterrows():
        symbol, date = row["symbol"], row["date"]
        near_ca = _near_corporate_action(symbol, date, corporate_action_dates, grace_days)
        price_tol = tol["price_relative_pct"] / 100.0
        vol_tol = tol["volume_relative_pct"] / 100.0
        if near_ca:
            price_tol *= 5  # widen substantially around a known corporate action
            vol_tol *= 3

        mismatches = []
        for field in _COMPARE_COLUMNS:
            a, b = row[f"{field}_primary"], row[f"{field}_secondary"]
            if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
                continue
            rel_diff = abs(a - b) / abs(a)
            if rel_diff > price_tol:
                mismatches.append((field, rel_diff))

        a, b = row["volume_primary"], row["volume_secondary"]
        if not (pd.isna(a) or pd.isna(b)) and max(a, b) > 0:
            rel_diff = abs(a - b) / max(abs(a), abs(b))
            if rel_diff > vol_tol:
                mismatches.append(("volume", rel_diff))

        rows.append({
            "symbol": symbol, "date": date, "near_corporate_action": near_ca,
            "mismatch": len(mismatches) > 0, "mismatched_fields": [m[0] for m in mismatches],
            "max_relative_diff": max((m[1] for m in mismatches), default=0.0),
        })

    return pd.DataFrame(rows)


def _near_corporate_action(symbol: str, date: pd.Timestamp, ca_dates: dict[str, set], grace_days: int) -> bool:
    dates = ca_dates.get(symbol)
    if not dates:
        return False
    return any(abs((date - pd.Timestamp(d)).days) <= grace_days for d in dates)


def validate_cross_source(
    primary: pd.DataFrame,
    secondary: pd.DataFrame | None,
    market: str,
    cfg: dict,
    corporate_action_dates: dict[str, set] | None = None,
) -> CheckResult:
    require_secondary = cfg["cross_source"]["require_secondary"]

    if secondary is None or secondary.empty:
        if require_secondary:
            return CheckResult(
                "cross_source", mandatory=True, passed=False,
                issues=[ValidationIssue("cross_source", "FATAL", "No secondary-source data available for comparison", market)],
                details={"secondary_available": False},
            )
        # secondary genuinely optional and absent this run -- not a failure,
        # and not counted as a passed mandatory check either (it is simply
        # not applicable) so the report can show it as SKIPPED rather than
        # implying two sources actually agreed.
        return CheckResult("cross_source", mandatory=False, passed=True, issues=[],
                            details={"secondary_available": False, "status": "SKIPPED"})

    comparison = compare_sources(primary, secondary, cfg, corporate_action_dates)
    if comparison.empty:
        return CheckResult("cross_source", mandatory=False, passed=True, issues=[],
                            details={"secondary_available": True, "overlapping_rows": 0, "status": "NO_OVERLAP"})

    mismatches = comparison[comparison["mismatch"]]
    issues = [
        ValidationIssue(
            "cross_source", "FATAL",
            f"SOURCE_MISMATCH on fields {row['mismatched_fields']} "
            f"(max relative diff {row['max_relative_diff']:.1%}, near_corporate_action={row['near_corporate_action']})",
            market, row["symbol"], str(row["date"].date()),
        )
        for _, row in mismatches.head(50).iterrows()
    ]

    passed = len(mismatches) == 0
    return CheckResult("cross_source", mandatory=True, passed=passed, issues=issues,
                        details={
                            "secondary_available": True,
                            "overlapping_rows": len(comparison),
                            "mismatched_rows": len(mismatches),
                            "agreement_rate": round(1 - len(mismatches) / len(comparison), 4) if len(comparison) else 1.0,
                        })
