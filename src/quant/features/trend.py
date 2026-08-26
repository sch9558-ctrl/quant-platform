"""Trend features (spec section 5, "Trend"): SMA, EMA, MA distance, MA
cross, ADX. All rolling/ewm operations use the default (non-centered)
window, so every value at row t depends only on rows <= t.
"""
from __future__ import annotations

import pandas as pd
import ta.trend as ta_trend


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean().rename(f"sma_{window}")


def ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False, min_periods=window).mean().rename(f"ema_{window}")


def ma_distance(close: pd.Series, window: int, kind: str = "sma") -> pd.Series:
    """(price - MA) / MA -- how far price has stretched from its moving average."""
    ma = sma(close, window) if kind == "sma" else ema(close, window)
    return ((close - ma) / ma).rename(f"{kind}_dist_{window}")


def ma_cross(close: pd.Series, fast: int, slow: int, kind: str = "sma") -> pd.DataFrame:
    """Dual moving average cross: signed spread and a discrete cross signal.

    cross_signal: +1 when fast > slow (bullish alignment), -1 otherwise.
    cross_event: +1 on the bar the fast MA crosses above the slow MA,
                 -1 on the bar it crosses below, 0 otherwise.
    """
    fast_ma = sma(close, fast) if kind == "sma" else ema(close, fast)
    slow_ma = sma(close, slow) if kind == "sma" else ema(close, slow)
    spread = (fast_ma - slow_ma) / slow_ma
    cross_signal = spread.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    prev_signal = cross_signal.shift(1).fillna(0)
    cross_event = ((cross_signal == 1) & (prev_signal <= 0)).astype(int) - \
                  ((cross_signal == -1) & (prev_signal >= 0)).astype(int)
    return pd.DataFrame({
        f"ma_cross_spread_{fast}_{slow}": spread,
        f"ma_cross_signal_{fast}_{slow}": cross_signal,
        f"ma_cross_event_{fast}_{slow}": cross_event,
    })


def adx(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average Directional Index using high/low/close (trend strength, not direction)."""
    indicator = ta_trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"],
                                       window=window, fillna=False)
    return indicator.adx().rename(f"adx_{window}")
