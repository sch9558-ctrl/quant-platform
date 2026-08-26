"""Fundamental features (spec section 5, "Fundamentals").

Fundamentals here are cross-sectional (one snapshot per `as_of` date, as
returned by `MarketDataProvider.get_fundamentals`) rather than a daily time
series, since neither pykrx nor yfinance expose fully point-in-time
fundamental history for free. Where a strategy needs point-in-time
fundamentals, call `get_fundamentals(symbols, as_of=<backtest date>)` at
each rebalance date rather than caching a single "current" snapshot across
the whole backtest -- that discipline is enforced by callers in
`strategy/factor.py`, not by this module.

This module turns raw fundamental levels into cross-sectionally comparable,
correctly-signed scores (e.g. cheaper PER/PBR = higher Value score).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# columns where a LOWER raw value is fundamentally "better" (cheaper /
# less levered); these are sign-flipped before z-scoring so that, after
# transformation, higher score = more attractive on every column.
_LOWER_IS_BETTER = {"per", "pbr", "debt_ratio"}


def winsorize(s: pd.Series, limits: tuple[float, float] = (0.01, 0.01)) -> pd.Series:
    lo, hi = s.quantile(limits[0]), s.quantile(1 - limits[1])
    return s.clip(lower=lo, upper=hi)


def cross_sectional_zscore(fund_df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Z-score each fundamental column cross-sectionally (across symbols at
    one `as_of` date), winsorizing tails first, and sign-flipping columns in
    `_LOWER_IS_BETTER` so every output column is oriented "higher = better".
    """
    columns = columns or [c for c in fund_df.columns if c not in ("market_cap",)]
    out = {}
    for col in columns:
        if col not in fund_df.columns:
            continue
        s = pd.to_numeric(fund_df[col], errors="coerce")
        if s.notna().sum() < 3:
            out[f"{col}_z"] = pd.Series(np.nan, index=fund_df.index)
            continue
        s = winsorize(s.dropna()).reindex(s.index)
        z = (s - s.mean()) / s.std(ddof=0)
        if col in _LOWER_IS_BETTER:
            z = -z
        out[f"{col}_z"] = z
    return pd.DataFrame(out, index=fund_df.index)


def value_score(fund_df: pd.DataFrame) -> pd.Series:
    z = cross_sectional_zscore(fund_df, columns=["per", "pbr"])
    return z.mean(axis=1, skipna=True).rename("value_score")


def quality_score(fund_df: pd.DataFrame) -> pd.Series:
    z = cross_sectional_zscore(fund_df, columns=["roe", "operating_margin", "debt_ratio"])
    return z.mean(axis=1, skipna=True).rename("quality_score")


def growth_score(fund_df: pd.DataFrame) -> pd.Series:
    z = cross_sectional_zscore(fund_df, columns=["eps_growth", "revenue_growth"])
    return z.mean(axis=1, skipna=True).rename("growth_score")


def dividend_score(fund_df: pd.DataFrame) -> pd.Series:
    z = cross_sectional_zscore(fund_df, columns=["dividend_yield"])
    return z.iloc[:, 0].rename("dividend_score") if not z.empty else pd.Series(dtype=float, name="dividend_score")


def build_fundamental_score_series(
    provider,
    symbols: list[str],
    dates: pd.DatetimeIndex,
    rebalance_dates: list[str] | pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    """Build a daily (forward-filled) time series of fundamental scores per
    symbol, by actually querying `provider.get_fundamentals` only at
    `rebalance_dates` (e.g. monthly) and holding each snapshot's scores
    constant until the next rebalance date.

    This is NOT look-ahead: between two rebalance dates we only ever
    forward-fill a value that was already known at the earlier date. It
    mirrors reality too -- fundamentals (EPS, revenue, etc.) update
    discretely with quarterly filings, not continuously.
    """
    snapshots: dict[pd.Timestamp, pd.DataFrame] = {}
    for d in sorted(pd.Timestamp(x) for x in rebalance_dates):
        fund_df = provider.get_fundamentals(symbols, d.strftime("%Y-%m-%d"))
        if fund_df is None or fund_df.empty:
            continue
        snapshots[d] = pd.DataFrame({
            "value_score": value_score(fund_df),
            "quality_score": quality_score(fund_df),
            "growth_score": growth_score(fund_df),
            "size_score": size_score(fund_df),
            "dividend_score": dividend_score(fund_df),
        })

    if not snapshots:
        return {}

    all_dates = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in dates))
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        rows = []
        for d, df in sorted(snapshots.items()):
            if sym in df.index:
                rows.append(df.loc[sym].rename(d))
        if not rows:
            continue
        sym_snap_df = pd.DataFrame(rows).sort_index()
        combined_idx = all_dates.union(sym_snap_df.index)
        sym_ts = sym_snap_df.reindex(combined_idx).ffill()
        out[sym] = sym_ts.reindex(all_dates)
    return out


def size_score(fund_df: pd.DataFrame) -> pd.Series:
    """Small-cap tilt: higher score = smaller market cap (the classic Size
    factor direction), using log market cap to reduce skew before z-scoring.
    """
    if "market_cap" not in fund_df.columns:
        return pd.Series(dtype=float, name="size_score")
    log_cap = np.log(pd.to_numeric(fund_df["market_cap"], errors="coerce").clip(lower=1))
    z = (log_cap - log_cap.mean()) / log_cap.std(ddof=0)
    return (-z).rename("size_score")
