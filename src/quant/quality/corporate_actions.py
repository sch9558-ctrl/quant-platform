"""Corporate Action handling (spec sections 4, 12).

Two responsibilities:

1. `corporate_action_dates` -- extract, per symbol, the set of dates that
   carry a recorded split or dividend event. `ohlc.classify_outliers` uses
   this to avoid mistaking a real 2-for-1 split (price roughly halves
   overnight) for a data error.

2. `validate_corporate_action_consistency` -- when a split factor *is*
   recorded, sanity-check that the raw close-to-close price ratio is at
   least roughly consistent with it. A split recorded as 2-for-1 next to a
   close price that didn't move at all is a sign the split was recorded on
   the wrong date, applied twice, or not actually reflected in the raw
   price series -- exactly the kind of silent inconsistency spec section 12
   asks to catch rather than paper over.
"""
from __future__ import annotations

import pandas as pd

from quant.quality.models import CheckResult, ValidationIssue

# how far the observed close-to-close ratio may deviate from the recorded
# split factor's implied ratio before it's flagged -- generous, because
# ordinary price movement on the same day adds noise on top of the split
_SPLIT_RATIO_WARN_TOLERANCE = 0.5    # 50% relative deviation -> WARNING
_SPLIT_RATIO_FATAL_TOLERANCE = 0.8   # 80% relative deviation -> FATAL (looks unapplied/mis-dated)


def corporate_action_dates(df: pd.DataFrame) -> dict[str, set]:
    """{symbol: {dates with a recorded split != 1 or a recorded dividend > 0}}."""
    out: dict[str, set] = {}
    if df is None or df.empty:
        return out

    has_split = "split" in df.columns
    has_dividend = "dividend" in df.columns
    if not has_split and not has_dividend:
        return out

    for symbol, g in df.groupby("symbol"):
        dates = set()
        if has_split:
            split_events = g.loc[g["split"].notna() & (g["split"] != 1.0), "date"]
            dates |= set(pd.to_datetime(split_events))
        if has_dividend:
            div_events = g.loc[g["dividend"].notna() & (g["dividend"] > 0), "date"]
            dates |= set(pd.to_datetime(div_events))
        if dates:
            out[symbol] = dates
    return out


def validate_corporate_action_consistency(df: pd.DataFrame, market: str) -> CheckResult:
    issues: list[ValidationIssue] = []

    if df is None or df.empty or "split" not in df.columns:
        return CheckResult("corporate_action_consistency", mandatory=True, passed=True, issues=[],
                            details={"splits_checked": 0})

    n_checked = 0
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("date").reset_index(drop=True)
        split_rows = g.index[g["split"].notna() & (g["split"] != 1.0)]
        for idx in split_rows:
            if idx == 0:
                continue  # no prior close to compare against
            n_checked += 1
            split_factor = float(g.loc[idx, "split"])
            prev_close, cur_close = float(g.loc[idx - 1, "close"]), float(g.loc[idx, "close"])
            if prev_close <= 0 or split_factor <= 0:
                continue
            observed_ratio = cur_close / prev_close
            expected_ratio = 1.0 / split_factor
            rel_dev = abs(observed_ratio - expected_ratio) / expected_ratio

            if rel_dev > _SPLIT_RATIO_FATAL_TOLERANCE:
                issues.append(ValidationIssue(
                    "corporate_action_consistency", "FATAL",
                    f"Recorded {split_factor}:1 split implies close ratio ~{expected_ratio:.3f}, "
                    f"observed {observed_ratio:.3f} ({rel_dev:.0%} deviation) on {g.loc[idx, 'date']}",
                    market, symbol, str(g.loc[idx, "date"]),
                ))
            elif rel_dev > _SPLIT_RATIO_WARN_TOLERANCE:
                issues.append(ValidationIssue(
                    "corporate_action_consistency", "WARNING",
                    f"Recorded {split_factor}:1 split implies close ratio ~{expected_ratio:.3f}, "
                    f"observed {observed_ratio:.3f} ({rel_dev:.0%} deviation) on {g.loc[idx, 'date']}",
                    market, symbol, str(g.loc[idx, "date"]),
                ))

    passed = not any(i.severity == "FATAL" for i in issues)
    return CheckResult("corporate_action_consistency", mandatory=True, passed=passed, issues=issues,
                        details={"splits_checked": n_checked})
