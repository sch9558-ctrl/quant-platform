"""OHLC Integrity + Outlier Detection (spec sections 4, 13).

Two distinct things happen here, deliberately kept separate:

1. `validate_ohlc_integrity` -- hard, zero-tolerance structural rules
   (high >= open/close/low, low <= open/close, volume >= 0, price > 0).
   These are never "auto-corrected"; a violating row is FATAL and the
   symbol is quarantined for that batch (spec section 4: "잘못된 OHLC
   데이터는 자동 수정하지 않는다. Quarantine 처리한다.").

2. `classify_outliers` -- statistical/behavioral anomalies (abnormal
   single-day moves, price discontinuities) that are *not* structurally
   invalid but warrant review. Every row gets one of four statuses:
   VALID / REVIEW / QUARANTINED / REJECTED (spec section 13). A move that
   lines up with a known corporate action is not penalized -- see
   `corporate_actions.py`, which this module accepts an (optional) explained
   set of dates from.
"""
from __future__ import annotations

import pandas as pd

from quant.quality.models import CheckResult, OutlierStatus, ValidationIssue


def validate_ohlc_integrity(df: pd.DataFrame, market: str) -> CheckResult:
    """Hard OHLC structural rules over the long record table (one row per
    symbol/date). Zero tolerance -- any violation is FATAL."""
    issues: list[ValidationIssue] = []

    if df is None or df.empty:
        return CheckResult("ohlc_integrity", mandatory=True, passed=True, issues=[],
                            details={"rows_checked": 0})

    def _flag(mask: pd.Series, check: str, message: str) -> None:
        if not mask.any():
            return
        bad = df.loc[mask]
        for _, row in bad.head(50).iterrows():  # cap detail volume; count is still accurate
            issues.append(ValidationIssue(
                check, "FATAL", message, market, str(row.get("symbol")), str(row.get("date")),
            ))

    _flag(df["high"] < df["open"], "ohlc_integrity", "high < open")
    _flag(df["high"] < df["close"], "ohlc_integrity", "high < close")
    _flag(df["high"] < df["low"], "ohlc_integrity", "high < low")
    _flag(df["low"] > df["open"], "ohlc_integrity", "low > open")
    _flag(df["low"] > df["close"], "ohlc_integrity", "low > close")
    _flag(df["volume"] < 0, "ohlc_integrity", "negative volume")
    _flag((df[["open", "high", "low", "close"]] <= 0).any(axis=1), "ohlc_integrity", "non-positive price")

    passed = len(issues) == 0
    return CheckResult("ohlc_integrity", mandatory=True, passed=passed, issues=issues,
                        details={"rows_checked": len(df), "violations": len(issues)})


def classify_outliers(
    df: pd.DataFrame,
    cfg: dict,
    corporate_action_dates: dict[str, set] | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Classify every row of a *single symbol's* sorted long-format slice
    (or a full multi-symbol table -- grouped internally by `symbol`) into
    VALID / REVIEW / QUARANTINED / REJECTED, returning the table with a new
    `outlier_status` column plus a count per status.

    - VALID: |daily return| within `valid_max_abs_return`.
    - REVIEW: beyond that but within `review_max_abs_return`, OR explained
      by a known corporate action on that date (downgraded from REJECTED).
    - REJECTED: beyond `review_max_abs_return` with no corporate-action
      explanation -- not automatically used by strategies/backtests.
    - QUARANTINED: reserved for rows that failed hard OHLC integrity (set
      by the caller, `engine.py`, after `validate_ohlc_integrity` runs;
      this function does not assign it itself).
    """
    corporate_action_dates = corporate_action_dates or {}
    valid_max = cfg["outlier"]["valid_max_abs_return"]
    review_max = cfg["outlier"]["review_max_abs_return"]

    if df is None or df.empty:
        out = df.copy() if df is not None else pd.DataFrame()
        if not out.empty:
            out["outlier_status"] = pd.Series(dtype="object")
        return out, {"VALID": 0, "REVIEW": 0, "QUARANTINED": 0, "REJECTED": 0}

    out_parts = []
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("date").copy()
        ret = g["close"].pct_change().abs()
        ca_dates = corporate_action_dates.get(symbol, set())
        dates = pd.to_datetime(g["date"])

        status = pd.Series("VALID", index=g.index)
        review_mask = (ret > valid_max) & (ret <= review_max)
        reject_mask = ret > review_max
        explained_mask = pd.Series([d in ca_dates for d in dates], index=g.index)

        status[review_mask] = "REVIEW"
        status[reject_mask & ~explained_mask] = "REJECTED"
        status[reject_mask & explained_mask] = "REVIEW"  # explained by a corporate action -- downgraded

        g["outlier_status"] = status
        out_parts.append(g)

    out = pd.concat(out_parts, ignore_index=True) if out_parts else df
    counts = out["outlier_status"].value_counts().to_dict()
    for s in ("VALID", "REVIEW", "QUARANTINED", "REJECTED"):
        counts.setdefault(s, 0)
    return out, {k: int(v) for k, v in counts.items()}
