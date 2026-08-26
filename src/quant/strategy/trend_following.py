"""Trend Following strategies (spec section 6)."""
from __future__ import annotations

import pandas as pd

from quant.features import trend as trend_feat
from quant.strategy.base import BaseStrategy, stateful_long_flat


class MovingAverageStrategy(BaseStrategy):
    """Single moving average: long while price is above its MA."""
    id = "moving_average"
    family = "trend_following"

    def __init__(self, window: int = 100):
        super().__init__(window=window)
        self.window = window

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            ma = trend_feat.sma(df["close"], self.window)
            signals[sym] = (df["close"] > ma).astype(float)
        return self._combine_signals(signals)


class DualMovingAverageStrategy(BaseStrategy):
    """Classic fast/slow moving-average crossover: long while fast > slow."""
    id = "ma_crossover"
    family = "trend_following"

    def __init__(self, fast_window: int = 20, slow_window: int = 60):
        super().__init__(fast_window=fast_window, slow_window=slow_window)
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            fast = trend_feat.sma(df["close"], self.fast_window)
            slow = trend_feat.sma(df["close"], self.slow_window)
            signals[sym] = (fast > slow).astype(float)
        return self._combine_signals(signals)


class DonchianBreakoutStrategy(BaseStrategy):
    """Donchian channel breakout: enter long on a new `entry_window`-day
    high, exit on a new `exit_window`-day low (classic turtle-style system).
    """
    id = "donchian_breakout"
    family = "trend_following"

    def __init__(self, entry_window: int = 55, exit_window: int = 20):
        super().__init__(entry_window=entry_window, exit_window=exit_window)
        self.entry_window = entry_window
        self.exit_window = exit_window

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            high, low, close = df["high"], df["low"], df["close"]
            # shift(1): the breakout level is the prior N-day extreme,
            # excluding today's own bar, so today's close can legitimately
            # trigger a breakout against yesterday's known channel.
            entry_level = high.rolling(self.entry_window, min_periods=self.entry_window).max().shift(1)
            exit_level = low.rolling(self.exit_window, min_periods=self.exit_window).min().shift(1)
            entry = close > entry_level
            exit_ = close < exit_level
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)
