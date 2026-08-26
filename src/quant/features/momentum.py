"""Momentum features (spec section 5, "Momentum"): ROC, RSI, MACD, Relative
Strength vs. benchmark, and cross-sectional momentum rank (panel-level,
computed in features/engine.py since it needs the whole universe at once).
"""
from __future__ import annotations

import pandas as pd
import ta.momentum as ta_mom
import ta.trend as ta_trend


def roc(close: pd.Series, window: int) -> pd.Series:
    return (close / close.shift(window) - 1).rename(f"roc_{window}")


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    return ta_mom.RSIIndicator(close=close, window=window, fillna=False).rsi().rename(f"rsi_{window}")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ind = ta_trend.MACD(close=close, window_fast=fast, window_slow=slow, window_sign=signal, fillna=False)
    return pd.DataFrame({
        "macd": ind.macd(),
        "macd_signal": ind.macd_signal(),
        "macd_diff": ind.macd_diff(),
    })


def relative_strength(close: pd.Series, benchmark_close: pd.Series, window: int = 126) -> pd.Series:
    """Momentum of `close` relative to a benchmark index over `window` days:
    (asset return) - (benchmark return) over the trailing window. Positive
    values mean the asset has been outperforming the benchmark.
    """
    bench_aligned = benchmark_close.reindex(close.index).ffill()
    asset_ret = close / close.shift(window) - 1
    bench_ret = bench_aligned / bench_aligned.shift(window) - 1
    return (asset_ret - bench_ret).rename(f"rel_strength_{window}")


def cross_sectional_momentum_rank(returns_by_symbol: pd.DataFrame) -> pd.DataFrame:
    """Given a DataFrame indexed by date with one return column per symbol
    (e.g. each symbol's trailing N-day return on that date), return the
    cross-sectional percentile rank (0=worst, 1=best) computed independently
    for each date/row -- i.e. only using information available on that date,
    across whichever symbols already existed then (NaN for the rest).
    """
    return returns_by_symbol.rank(axis=1, pct=True, na_option="keep")
