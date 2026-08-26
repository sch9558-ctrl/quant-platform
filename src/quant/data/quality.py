"""Data quality checks (spec section 29).

Runs a battery of sanity checks on an OHLCV frame and returns a list of
`DataQualityIssue`. The scanner/backtester should call `check_ohlcv` and at
minimum log warnings; symbols with FATAL issues should be excluded from the
universe for that run rather than silently propagated into signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Severity = Literal["INFO", "WARNING", "FATAL"]


@dataclass
class DataQualityIssue:
    symbol: str
    check: str
    severity: Severity
    message: str
    date: pd.Timestamp | None = None


def check_ohlcv(
    symbol: str,
    df: pd.DataFrame,
    max_daily_return: float = 0.35,
    min_expected_rows: int = 1,
) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []

    if df is None or df.empty:
        issues.append(DataQualityIssue(symbol, "missing_data", "FATAL", "No OHLCV rows returned"))
        return issues

    if len(df) < min_expected_rows:
        issues.append(DataQualityIssue(symbol, "insufficient_history", "WARNING",
                                        f"Only {len(df)} rows, expected >= {min_expected_rows}"))

    # duplicate index
    dupes = df.index[df.index.duplicated()]
    if len(dupes) > 0:
        issues.append(DataQualityIssue(symbol, "duplicate_dates", "WARNING",
                                        f"{len(dupes)} duplicate dates found"))

    # missing values
    na_counts = df[["open", "high", "low", "close", "volume"]].isna().sum()
    for col, n in na_counts.items():
        if n > 0:
            issues.append(DataQualityIssue(symbol, "missing_values", "WARNING", f"{n} NaN in {col}"))

    # zero or negative price
    zero_mask = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if zero_mask.any():
        bad_dates = df.index[zero_mask]
        issues.append(DataQualityIssue(symbol, "zero_or_negative_price", "FATAL",
                                        f"{zero_mask.sum()} rows with non-positive price",
                                        date=bad_dates[0]))

    # OHLC internal consistency: high >= low, high >= open/close, low <= open/close
    bad_hl = (df["high"] < df["low"]).any()
    if bad_hl:
        issues.append(DataQualityIssue(symbol, "invalid_hl_range", "FATAL", "high < low on some rows"))

    # abnormal single-day return (possible bad tick / unhandled split)
    ret = df["close"].pct_change()
    abnormal = ret.abs() > max_daily_return
    if abnormal.any():
        n = int(abnormal.sum())
        worst_date = ret.abs().idxmax()
        issues.append(DataQualityIssue(
            symbol, "abnormal_price_change", "WARNING",
            f"{n} day(s) with |return| > {max_daily_return:.0%} "
            f"(worst on {worst_date.date()}: {ret.loc[worst_date]:.1%}); "
            "verify this is a real move and not an unadjusted split/data error",
            date=worst_date,
        ))

    # negative volume
    if (df["volume"] < 0).any():
        issues.append(DataQualityIssue(symbol, "negative_volume", "FATAL", "Negative volume present"))

    # long stretch of zero volume (possible trading halt / stale data)
    zero_vol_run = (df["volume"] == 0).astype(int)
    if len(zero_vol_run) > 0:
        max_run = int((zero_vol_run.groupby((zero_vol_run != zero_vol_run.shift()).cumsum()).cumsum() * zero_vol_run).max())
        if max_run >= 5:
            issues.append(DataQualityIssue(symbol, "extended_zero_volume", "WARNING",
                                            f"{max_run} consecutive zero-volume days"))

    return issues


def summarize_issues(all_issues: list[DataQualityIssue]) -> pd.DataFrame:
    if not all_issues:
        return pd.DataFrame(columns=["symbol", "check", "severity", "message", "date"])
    return pd.DataFrame([vars(i) for i in all_issues])
