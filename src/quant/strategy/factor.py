"""Factor strategies (spec section 6). These require fundamental score
columns ("value_score", "quality_score", "growth_score", "size_score",
"dividend_score") to already be attached to each symbol's feature DataFrame
via `FeatureEngine.attach_fundamental_scores` (built from
`features.fundamental.build_fundamental_score_series`) -- they are not
computed from `ohlcv_map` alone.
"""
from __future__ import annotations

import pandas as pd

from quant.strategy.base import BaseStrategy, cross_sectional_select


class _FundamentalRankStrategy(BaseStrategy):
    """Shared implementation: rank the average of one or more fundamental
    score columns cross-sectionally, go long the top `top_pct`."""
    score_columns: tuple[str, ...] = ()

    def __init__(self, top_pct: float = 0.2):
        super().__init__(top_pct=top_pct)
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        if not feature_map:
            raise ValueError(f"{self.__class__.__name__} requires feature_map with fundamental scores attached")
        combined = {}
        for sym, feat_df in feature_map.items():
            cols = [c for c in self.score_columns if c in feat_df.columns]
            if not cols:
                continue
            combined[sym] = feat_df[cols].mean(axis=1)
        if not combined:
            return pd.DataFrame()
        wide = pd.DataFrame(combined)
        return cross_sectional_select(wide, self.top_pct)


class ValueFactorStrategy(_FundamentalRankStrategy):
    id = "value_factor"
    family = "factor"
    score_columns = ("value_score",)


class QualityFactorStrategy(_FundamentalRankStrategy):
    id = "quality_factor"
    family = "factor"
    score_columns = ("quality_score",)


class LowVolatilityFactorStrategy(BaseStrategy):
    """Classic Low-Volatility factor: go long the lowest-volatility
    `top_pct` fraction of the universe (uses technical `hvol_20`, computed
    by FeatureEngine, not a fundamental score)."""
    id = "low_vol_factor"
    family = "factor"

    def __init__(self, top_pct: float = 0.2):
        super().__init__(top_pct=top_pct)
        self.top_pct = top_pct

    def generate_weights(self, ohlcv_map, feature_map=None, benchmark_close=None) -> pd.DataFrame:
        if not feature_map:
            raise ValueError("LowVolatilityFactorStrategy requires feature_map with hvol_20")
        inv_vol = {}
        for sym, feat_df in feature_map.items():
            if "hvol_20" in feat_df.columns:
                inv_vol[sym] = -feat_df["hvol_20"]  # lower vol -> higher score
        if not inv_vol:
            return pd.DataFrame()
        wide = pd.DataFrame(inv_vol)
        return cross_sectional_select(wide, self.top_pct)


class SizeFactorStrategy(_FundamentalRankStrategy):
    id = "size_factor"
    family = "factor"
    score_columns = ("size_score",)


class ValueQualityFactorStrategy(_FundamentalRankStrategy):
    """Combined Value + Quality factor (spec section 6, "Multi-Factor"
    example is listed under Factor here since it only mixes fundamental
    columns; see multi_factor.py for factors that also mix in price-based
    signals like momentum)."""
    id = "value_quality"
    family = "factor"
    score_columns = ("value_score", "quality_score")
