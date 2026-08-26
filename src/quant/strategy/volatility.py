"""Volatility strategies (spec section 6): Volatility Breakout, ATR
Breakout, Volatility Contraction.
"""
from __future__ import annotations

import pandas as pd

from quant.features import volatility as vol_feat
from quant.strategy.base import BaseStrategy, stateful_long_flat


class VolatilityBreakoutStrategy(BaseStrategy):
    """Larry Williams-style range breakout: go long when today's close
    clears yesterday's close by more than `k` x yesterday's ATR. Stays long
    until price falls back below yesterday's close level (trend exhausted).
    """
    id = "volatility_breakout"
    family = "volatility"

    def __init__(self, atr_window: int = 20, k: float = 0.5):
        super().__init__(atr_window=atr_window, k=k)
        self.atr_window = atr_window
        self.k = k

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            close = df["close"]
            atr_prev = vol_feat.atr(df, self.atr_window).shift(1)
            breakout_level = close.shift(1) + self.k * atr_prev
            entry = close > breakout_level
            exit_ = close < close.shift(1)
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)


class ATRBreakoutStrategy(BaseStrategy):
    """Enter long on a close beyond `k` ATRs above the `window`-day moving
    average (a volatility-normalized breakout band), exit on reversion back
    inside the band.
    """
    id = "atr_breakout"
    family = "volatility"

    def __init__(self, window: int = 20, k: float = 1.5):
        super().__init__(window=window, k=k)
        self.window = window
        self.k = k

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            close = df["close"]
            ma = close.rolling(self.window, min_periods=self.window).mean()
            atr = vol_feat.atr(df, self.window)
            upper = ma + self.k * atr
            entry = close > upper
            exit_ = close < ma
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)


class VolatilityContractionStrategy(BaseStrategy):
    """"Squeeze then breakout": require Bollinger Band width to be in its
    own bottom `contraction_percentile` of the trailing year (a volatility
    squeeze) before a `breakout_window`-day high breakout is allowed to
    trigger an entry. Exits on a `breakout_window`-day low.
    """
    id = "vol_contraction"
    family = "volatility"

    def __init__(self, bb_window: int = 20, contraction_percentile: float = 0.2, breakout_window: int = 20):
        super().__init__(bb_window=bb_window, contraction_percentile=contraction_percentile,
                          breakout_window=breakout_window)
        self.bb_window = bb_window
        self.contraction_percentile = contraction_percentile
        self.breakout_window = breakout_window

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            close, high, low = df["close"], df["high"], df["low"]
            width = vol_feat.bollinger_band_width(close, self.bb_window)
            # trailing-year percentile rank of today's band width -- vectorized
            # via `.rolling().rank(pct=True)` rather than a Python-level
            # `.apply(lambda ...)` per window, which is ~7x faster at this
            # universe size and produces the same "how low is this squeeze,
            # relative to the trailing year" signal (functionally equivalent
            # to `(w.iloc[-1] > w).mean()`, modulo tie-handling).
            width_percentile = width.rolling(252, min_periods=60).rank(pct=True)
            in_squeeze = width_percentile <= self.contraction_percentile
            entry_level = high.rolling(self.breakout_window, min_periods=self.breakout_window).max().shift(1)
            exit_level = low.rolling(self.breakout_window, min_periods=self.breakout_window).min().shift(1)
            entry = in_squeeze.shift(1).fillna(False) & (close > entry_level)
            exit_ = close < exit_level
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)
