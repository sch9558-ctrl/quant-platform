"""Volume features (spec section 5, "Volume"): Volume Ratio, Volume
Momentum, Abnormal Volume, Turnover.
"""
from __future__ import annotations

import pandas as pd


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    avg = volume.rolling(window, min_periods=window).mean()
    return (volume / avg).rename(f"vol_ratio_{window}")


def volume_momentum(volume: pd.Series, window: int = 20) -> pd.Series:
    avg = volume.rolling(window, min_periods=window).mean()
    return (avg / avg.shift(window) - 1).rename(f"vol_momentum_{window}")


def abnormal_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    """Z-score of today's volume vs. its trailing distribution."""
    avg = volume.rolling(window, min_periods=window).mean()
    sd = volume.rolling(window, min_periods=window).std()
    return ((volume - avg) / sd.replace(0, pd.NA)).rename(f"abn_vol_{window}")


def turnover(volume: pd.Series, shares_outstanding: float | pd.Series) -> pd.Series:
    """Daily turnover ratio = volume traded / shares outstanding."""
    return (volume / shares_outstanding).rename("turnover")
