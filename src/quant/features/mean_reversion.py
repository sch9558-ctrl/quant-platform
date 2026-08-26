"""Mean-reversion features (spec section 5): Z-Score, Distance from Moving
Average, Bollinger Position.
"""
from __future__ import annotations

import pandas as pd
import ta.volatility as ta_vol


def zscore(close: pd.Series, window: int = 20) -> pd.Series:
    mean = close.rolling(window, min_periods=window).mean()
    sd = close.rolling(window, min_periods=window).std()
    return ((close - mean) / sd.replace(0, pd.NA)).rename(f"zscore_{window}")


def distance_from_ma(close: pd.Series, window: int = 20) -> pd.Series:
    ma = close.rolling(window, min_periods=window).mean()
    return ((close - ma) / ma).rename(f"ma_dist_{window}")


def bollinger_position(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """0 = at lower band, 1 = at upper band, 0.5 = at the middle band."""
    ind = ta_vol.BollingerBands(close=close, window=window, window_dev=num_std, fillna=False)
    upper, lower = ind.bollinger_hband(), ind.bollinger_lband()
    pos = (close - lower) / (upper - lower)
    return pos.rename(f"bb_pos_{window}")
