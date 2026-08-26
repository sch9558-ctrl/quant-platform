"""Mean Reversion strategies (spec section 6): RSI Reversal, Bollinger
Reversion, Z-Score Reversion. All three are stateful long/flat systems:
enter on an oversold trigger, hold until a recovery trigger fires.
"""
from __future__ import annotations

import pandas as pd

from quant.features import mean_reversion as mr
from quant.features import momentum as mom
from quant.strategy.base import BaseStrategy, stateful_long_flat


class RSIReversalStrategy(BaseStrategy):
    id = "rsi_reversal"
    family = "mean_reversion"

    def __init__(self, rsi_window: int = 14, oversold: float = 30, overbought: float = 70):
        super().__init__(rsi_window=rsi_window, oversold=oversold, overbought=overbought)
        self.rsi_window = rsi_window
        self.oversold = oversold
        self.overbought = overbought

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            r = mom.rsi(df["close"], self.rsi_window)
            entry = r < self.oversold
            exit_ = r > self.overbought
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)


class BollingerReversionStrategy(BaseStrategy):
    id = "bollinger_reversion"
    family = "mean_reversion"

    def __init__(self, window: int = 20, num_std: float = 2.0):
        super().__init__(window=window, num_std=num_std)
        self.window = window
        self.num_std = num_std

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            pos = mr.bollinger_position(df["close"], self.window, self.num_std)
            entry = pos < 0.0       # closed below the lower band
            exit_ = pos > 0.5       # recovered back to the mid band
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)


class ZScoreReversionStrategy(BaseStrategy):
    id = "zscore_reversion"
    family = "mean_reversion"

    def __init__(self, window: int = 20, entry_z: float = -1.5, exit_z: float = 0.0):
        super().__init__(window=window, entry_z=entry_z, exit_z=exit_z)
        self.window = window
        self.entry_z = entry_z
        self.exit_z = exit_z

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        signals = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            z = mr.zscore(df["close"], self.window)
            entry = z < self.entry_z
            exit_ = z > self.exit_z
            signals[sym] = stateful_long_flat(entry, exit_)
        return self._combine_signals(signals)
