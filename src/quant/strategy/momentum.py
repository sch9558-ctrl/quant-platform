"""Momentum strategies (spec section 6): Time-Series Momentum,
Cross-Sectional Momentum, Relative Strength.
"""
from __future__ import annotations

import pandas as pd

from quant.strategy.base import BaseStrategy, cross_sectional_select


def trailing_return(close: pd.Series, lookback_days: int, skip_days: int = 0) -> pd.Series:
    """Return over the window ending `skip_days` before today (skipping the
    most recent days avoids the well-documented 1-week short-term reversal
    that would otherwise contaminate a pure momentum signal)."""
    far = close.shift(lookback_days + skip_days)
    near = close.shift(skip_days)
    return near / far - 1


class TimeSeriesMomentumStrategy(BaseStrategy):
    """Long a symbol whenever its own trailing return is positive (each
    symbol decided independently of the others -- this is "absolute"
    momentum, not a cross-sectional ranking).
    """
    id = "ts_momentum"
    family = "momentum"

    def __init__(self, lookback_days: int = 126, skip_days: int = 5):
        super().__init__(lookback_days=lookback_days, skip_days=skip_days)
        self.lookback_days = lookback_days
        self.skip_days = skip_days

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            ret = trailing_return(df["close"], self.lookback_days, self.skip_days)
            signals[sym] = (ret > 0).astype(float)
        return self._combine_signals(signals)


class CrossSectionalMomentumStrategy(BaseStrategy):
    """Rank all symbols by trailing return each day and go long the top
    `top_pct` fraction, equal-weighted among the selected names.
    """
    id = "cs_momentum"
    family = "momentum"

    def __init__(self, lookback_days: int = 126, skip_days: int = 5, top_pct: float = 0.2):
        super().__init__(lookback_days=lookback_days, skip_days=skip_days, top_pct=top_pct)
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        rets = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            rets[sym] = trailing_return(df["close"], self.lookback_days, self.skip_days)
        if not rets:
            return pd.DataFrame()
        wide = pd.DataFrame(rets)
        return cross_sectional_select(wide, self.top_pct)


class RelativeStrengthStrategy(BaseStrategy):
    """Long symbols outperforming the market benchmark over the lookback
    window (relative, rather than absolute or purely cross-sectional,
    momentum); requires `benchmark_close`.
    """
    id = "relative_strength"
    family = "momentum"

    def __init__(self, lookback_days: int = 126, top_pct: float = 0.3):
        super().__init__(lookback_days=lookback_days, top_pct=top_pct)
        self.lookback_days = lookback_days
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        if benchmark_close is None:
            raise ValueError("RelativeStrengthStrategy requires benchmark_close")
        rs = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            close = df["close"]
            bench = benchmark_close.reindex(close.index).ffill()
            asset_ret = trailing_return(close, self.lookback_days)
            bench_ret = bench / bench.shift(self.lookback_days) - 1
            rs[sym] = asset_ret - bench_ret
        if not rs:
            return pd.DataFrame()
        wide = pd.DataFrame(rs)
        return cross_sectional_select(wide, self.top_pct)
