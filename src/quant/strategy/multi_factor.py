"""Multi-Factor strategies (spec section 6): combine a price-based factor
(momentum, computed directly from `ohlcv_map`) with a fundamental factor
(quality, computed from attached fundamental score columns -- see
`strategy/factor.py` module docstring for how those get attached).
"""
from __future__ import annotations

import pandas as pd

from quant.features import volatility as vol_feat
from quant.strategy.base import BaseStrategy, cross_sectional_select
from quant.strategy.momentum import trailing_return


class MomentumQualityStrategy(BaseStrategy):
    id = "momentum_quality"
    family = "multi_factor"

    def __init__(self, momentum_lookback: int = 126, top_pct: float = 0.2):
        super().__init__(momentum_lookback=momentum_lookback, top_pct=top_pct)
        self.momentum_lookback = momentum_lookback
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        mom_scores = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            mom_scores[sym] = trailing_return(df["close"], self.momentum_lookback)
        if not mom_scores:
            return pd.DataFrame()
        mom_wide = pd.DataFrame(mom_scores)
        mom_rank = mom_wide.rank(axis=1, pct=True)

        if feature_map:
            quality = {sym: fd["quality_score"] for sym, fd in feature_map.items() if "quality_score" in fd.columns}
            if quality:
                quality_wide = pd.DataFrame(quality).reindex(mom_rank.index)
                quality_rank = quality_wide.rank(axis=1, pct=True)
                combined = mom_rank.add(quality_rank, fill_value=None) / 2
                return cross_sectional_select(combined, self.top_pct)

        # graceful fallback: momentum-only if no fundamental data is available
        return cross_sectional_select(mom_rank, self.top_pct)


class MomentumLowVolStrategy(BaseStrategy):
    id = "momentum_lowvol"
    family = "multi_factor"

    def __init__(self, momentum_lookback: int = 126, vol_lookback: int = 60, top_pct: float = 0.2):
        super().__init__(momentum_lookback=momentum_lookback, vol_lookback=vol_lookback, top_pct=top_pct)
        self.momentum_lookback = momentum_lookback
        self.vol_lookback = vol_lookback
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        mom_scores, vol_scores = {}, {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            mom_scores[sym] = trailing_return(df["close"], self.momentum_lookback)
            vol_scores[sym] = -vol_feat.historical_volatility(df["close"], self.vol_lookback)
        if not mom_scores:
            return pd.DataFrame()
        mom_rank = pd.DataFrame(mom_scores).rank(axis=1, pct=True)
        vol_rank = pd.DataFrame(vol_scores).reindex(mom_rank.index).rank(axis=1, pct=True)
        combined = (mom_rank + vol_rank) / 2
        return cross_sectional_select(combined, self.top_pct)


class ValueQualityMomentumStrategy(BaseStrategy):
    """Value + Quality + Momentum, the canonical three-factor blend from the
    spec's multi-factor example list."""
    id = "value_quality_momentum"
    family = "multi_factor"

    def __init__(self, momentum_lookback: int = 126, top_pct: float = 0.2):
        super().__init__(momentum_lookback=momentum_lookback, top_pct=top_pct)
        self.momentum_lookback = momentum_lookback
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        if not feature_map:
            raise ValueError("ValueQualityMomentumStrategy requires feature_map with fundamental scores attached")

        mom_scores = {}
        for sym, df in ohlcv_map.items():
            if df is None or df.empty:
                continue
            mom_scores[sym] = trailing_return(df["close"], self.momentum_lookback)
        if not mom_scores:
            return pd.DataFrame()
        mom_rank = pd.DataFrame(mom_scores).rank(axis=1, pct=True)

        vq = {}
        for sym, fd in feature_map.items():
            cols = [c for c in ("value_score", "quality_score") if c in fd.columns]
            if cols:
                vq[sym] = fd[cols].mean(axis=1)
        if not vq:
            return cross_sectional_select(mom_rank, self.top_pct)

        vq_rank = pd.DataFrame(vq).reindex(mom_rank.index).rank(axis=1, pct=True)
        combined = (mom_rank + vq_rank) / 2
        return cross_sectional_select(combined, self.top_pct)
