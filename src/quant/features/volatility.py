"""Volatility features (spec section 5, "Volatility"): Historical
Volatility, ATR, Bollinger Band Width, Downside Volatility.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import ta.volatility as ta_vol


def historical_volatility(close: pd.Series, window: int = 20, annualize: int = 252) -> pd.Series:
    ret = close.pct_change()
    return (ret.rolling(window, min_periods=window).std() * np.sqrt(annualize)).rename(f"hvol_{window}")


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    ind = ta_vol.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=window, fillna=False)
    return ind.average_true_range().rename(f"atr_{window}")


def atr_pct(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """ATR normalized by price, comparable across symbols/price levels."""
    return (atr(df, window) / df["close"]).rename(f"atr_pct_{window}")


def bollinger_band_width(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    ind = ta_vol.BollingerBands(close=close, window=window, window_dev=num_std, fillna=False)
    width = (ind.bollinger_hband() - ind.bollinger_lband()) / ind.bollinger_mavg()
    return width.rename(f"bb_width_{window}")


def downside_volatility(close: pd.Series, window: int = 20, annualize: int = 252) -> pd.Series:
    ret = close.pct_change()
    downside = ret.where(ret < 0, 0.0)
    return (downside.rolling(window, min_periods=window).std() * np.sqrt(annualize)).rename(f"downside_vol_{window}")
