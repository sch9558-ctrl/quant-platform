"""Schema Validation (spec section 3).

The Data Quality Engine operates on a "long" record table -- one row per
(market, symbol, date) -- rather than the per-symbol wide OHLCV frames the
rest of the pipeline (features/strategies/backtester) consumes. This is
deliberate: the spec's required schema (symbol, market, date, ..., currency,
source, retrieved_at) needs `source` and `retrieved_at` as explicit
per-row fields so cross-source comparison and audit trail can both key off
them directly, and a wide per-symbol frame has no natural place to put a
per-row provenance tag. `quality.adapters.to_long_records` builds this
table from the existing `MarketDataProvider.get_ohlcv_bulk` output; once
validated, `quality.adapters.to_ohlcv_map` reshapes the canonical result
back into the wide format everything downstream already expects.

This check runs first, before anything else even looks at the values,
since a missing column makes every downstream check meaningless.
"""
from __future__ import annotations

import pandas as pd

from quant.quality.models import CheckResult, ValidationIssue

REQUIRED_COLUMNS = ["symbol", "market", "date", "open", "high", "low", "close", "volume", "currency", "source", "retrieved_at"]
OPTIONAL_COLUMNS = ["adjusted_close", "dividend", "split", "market_cap"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]


def validate_schema(df: pd.DataFrame, market: str, cfg: dict) -> CheckResult:
    required = cfg.get("required_columns", REQUIRED_COLUMNS)
    numeric = cfg.get("numeric_columns", NUMERIC_COLUMNS)
    issues: list[ValidationIssue] = []

    if df is None:
        issues.append(ValidationIssue("schema", "FATAL", "Record table is None", market))
        return CheckResult("schema", mandatory=True, passed=False, issues=issues)

    if df.empty:
        issues.append(ValidationIssue("schema", "FATAL", "Record table is empty", market))
        return CheckResult("schema", mandatory=True, passed=False, issues=issues,
                            details={"required_columns": required, "found_columns": []})

    missing = [c for c in required if c not in df.columns]
    if missing:
        issues.append(ValidationIssue(
            "schema", "FATAL", f"Missing required column(s): {missing}", market,
        ))

    for col in numeric:
        if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
            issues.append(ValidationIssue(
                "schema", "FATAL", f"Column '{col}' is not numeric (dtype={df[col].dtype})", market,
            ))

    if "date" in df.columns:
        try:
            pd.to_datetime(df["date"])
        except Exception as e:
            issues.append(ValidationIssue("schema", "FATAL", f"Column 'date' is not parseable as dates: {e}", market))

    passed = not any(i.severity == "FATAL" for i in issues)
    return CheckResult("schema", mandatory=True, passed=passed, issues=issues,
                        details={"required_columns": required, "found_columns": sorted(df.columns)})
