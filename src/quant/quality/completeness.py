"""Duplicate / Missing Data / Freshness / Timezone validation (spec
sections 5-8).
"""
from __future__ import annotations

import pandas as pd

from quant.quality.models import CheckResult, ValidationIssue
from quant.utils import calendar as market_calendar


def validate_duplicates(df: pd.DataFrame, market: str, cfg: dict) -> CheckResult:
    """(market, symbol, date) must be a unique key (spec section 5). A
    duplicate is never silently resolved by picking one row -- its
    presence alone is a mandatory FAIL."""
    key_cols = cfg["duplicates"]["key_columns"]
    issues: list[ValidationIssue] = []

    if df is None or df.empty:
        return CheckResult("duplicates", mandatory=True, passed=True, issues=[], details={"duplicate_groups": 0})

    dup_mask = df.duplicated(subset=key_cols, keep=False)
    n_dupes = int(dup_mask.sum())
    if n_dupes:
        dup_rows = df.loc[dup_mask].sort_values(key_cols)
        for _, row in dup_rows.head(50).iterrows():
            issues.append(ValidationIssue(
                "duplicates", "FATAL",
                f"Duplicate row for key {tuple(row[c] for c in key_cols)}",
                market, str(row.get("symbol")), str(row.get("date")),
            ))

    passed = n_dupes == 0
    return CheckResult("duplicates", mandatory=True, passed=passed, issues=issues,
                        details={"duplicate_rows": n_dupes})


def validate_missing_sessions(
    df: pd.DataFrame,
    market: str,
    start: str,
    end: str,
    cfg: dict,
    listing_dates: dict[str, pd.Timestamp] | None = None,
    delisting_dates: dict[str, pd.Timestamp] | None = None,
) -> CheckResult:
    """Every symbol present in `df` must have a row for every real trading
    session (KRX/NYSE calendar, not weekday approximation) between
    `start` and `end`, except sessions before it was listed or after it
    was delisted (spec section 6)."""
    listing_dates = listing_dates or {}
    delisting_dates = delisting_dates or {}
    issues: list[ValidationIssue] = []
    total_missing = 0
    inferred_listing_boundaries: dict[str, str] = {}
    missing_by_symbol: dict[str, int] = {}
    internal_missing_by_symbol: dict[str, int] = {}
    trailing_missing_by_symbol: dict[str, int] = {}
    missing_by_date: dict[str, int] = {}

    if df is None or df.empty:
        issues.append(ValidationIssue("missing_sessions", "FATAL", "No data to check for missing sessions", market))
        return CheckResult("missing_sessions", mandatory=True, passed=False, issues=issues)

    all_expected = market_calendar.expected_sessions_between(start, end, market)

    for symbol, g in df.groupby("symbol"):
        present = pd.DatetimeIndex(pd.to_datetime(g["date"])).normalize()
        expected = all_expected
        listed = listing_dates.get(symbol)
        delisted = delisting_dates.get(symbol)
        if listed is not None and cfg["missing_sessions"]["allow_missing_before_listing"]:
            expected = expected[expected >= pd.Timestamp(listed).normalize()]
        elif listed is None and cfg["missing_sessions"]["allow_missing_before_listing"] and len(present):
            first_present = present.min()
            if len(all_expected) and first_present > all_expected.min():
                expected = expected[expected >= first_present]
                inferred_listing_boundaries[str(symbol)] = str(first_present.date())
        if delisted is not None and cfg["missing_sessions"]["allow_missing_after_delisting"]:
            expected = expected[expected <= pd.Timestamp(delisted).normalize()]

        missing = expected.difference(present)
        if len(missing) > 0:
            count = int(len(missing))
            total_missing += count
            symbol_key = str(symbol)
            missing_by_symbol[symbol_key] = count
            last_present = present.max() if len(present) else None
            if last_present is not None:
                internal_count = int((missing <= last_present).sum())
                trailing_count = int((missing > last_present).sum())
                if internal_count:
                    internal_missing_by_symbol[symbol_key] = internal_count
                if trailing_count:
                    trailing_missing_by_symbol[symbol_key] = trailing_count
            for d in missing:
                key = str(pd.Timestamp(d).date())
                missing_by_date[key] = missing_by_date.get(key, 0) + 1
            for d in missing[:20]:
                issues.append(ValidationIssue(
                    "missing_sessions", "FATAL",
                    f"No row for expected trading session {d.date()}",
                    market, symbol, str(d.date()),
                ))

    passed = total_missing == 0
    affected = len(missing_by_symbol)
    top_missing_dates = sorted(
        missing_by_date.items(), key=lambda item: (-item[1], item[0])
    )[:5]
    return CheckResult(
        "missing_sessions", mandatory=True, passed=passed, issues=issues,
        details={
            "total_missing_sessions": total_missing,
            "expected_sessions": len(all_expected),
            "symbols_checked": int(df["symbol"].nunique()),
            "symbols_with_missing": affected,
            "avg_missing_sessions_per_affected_symbol": (
                float(total_missing / affected) if affected else 0.0
            ),
            "top_missing_dates": [
                {"date": date, "symbols_missing": count}
                for date, count in top_missing_dates
            ],
            "missing_by_symbol": missing_by_symbol,
            "internal_missing_by_symbol": internal_missing_by_symbol,
            "trailing_missing_by_symbol": trailing_missing_by_symbol,
            "symbols_with_internal_missing": len(internal_missing_by_symbol),
            "symbols_with_trailing_missing": len(trailing_missing_by_symbol),
            "inferred_listing_boundaries": inferred_listing_boundaries,
        },
    )


def validate_freshness(
    df: pd.DataFrame, market: str, as_of: str, cfg: dict,
) -> CheckResult:
    """Data must be current as of the latest completed trading session
    (spec section 7) -- "today is a holiday" correctly rolls the
    expectation back to the prior session rather than flagging a false gap."""
    issues: list[ValidationIssue] = []
    latest_expected = market_calendar.latest_completed_session(market, as_of)
    max_lag = cfg["freshness"]["max_lag_sessions"]

    if df is None or df.empty:
        issues.append(ValidationIssue("freshness", "FATAL", "No data present to assess freshness", market))
        return CheckResult("freshness", mandatory=True, passed=False, issues=issues,
                            details={"latest_expected_session": str(latest_expected.date())})

    latest_present = pd.to_datetime(df["date"]).max().normalize()
    if latest_present < latest_expected:
        sessions_since = market_calendar.expected_sessions_between(
            latest_present.strftime("%Y-%m-%d"), latest_expected.strftime("%Y-%m-%d"), market,
        )
        lag = max(len(sessions_since) - 1, 0)  # includes both endpoints when present==expected
    else:
        lag = 0

    if latest_present < latest_expected and lag > max_lag:
        issues.append(ValidationIssue(
            "freshness", "FATAL",
            f"Latest data is {latest_present.date()} but latest completed session is "
            f"{latest_expected.date()} ({lag} session(s) stale, max allowed {max_lag})",
            market,
        ))

    passed = len(issues) == 0
    return CheckResult("freshness", mandatory=True, passed=passed, issues=issues,
                        details={
                            "latest_present_date": str(latest_present.date()),
                            "latest_expected_session": str(latest_expected.date()),
                            "lag_sessions": lag,
                        })


def validate_timezone(df: pd.DataFrame, market: str, cfg: dict) -> CheckResult:
    """`retrieved_at` must be an explicit, tz-aware timestamp (spec section
    8) -- naive datetimes are rejected outright since they are ambiguous
    about which wall-clock timezone they represent."""
    issues: list[ValidationIssue] = []

    if df is None or df.empty or "retrieved_at" not in df.columns:
        issues.append(ValidationIssue("timezone", "FATAL", "No 'retrieved_at' column to validate", market))
        return CheckResult("timezone", mandatory=True, passed=False, issues=issues)

    n_naive = 0
    for val in df["retrieved_at"].head(5000):  # cap: this is a per-batch check, not per-row-forever
        try:
            ts = pd.Timestamp(val)
        except Exception:
            issues.append(ValidationIssue("timezone", "FATAL", f"'retrieved_at' value not parseable: {val!r}", market))
            continue
        if ts.tzinfo is None:
            n_naive += 1

    if n_naive > 0:
        issues.append(ValidationIssue(
            "timezone", "FATAL", f"{n_naive} 'retrieved_at' value(s) are naive (no timezone) datetimes", market,
        ))

    passed = len(issues) == 0
    return CheckResult("timezone", mandatory=True, passed=passed, issues=issues,
                        details={"naive_timestamp_count": n_naive})
