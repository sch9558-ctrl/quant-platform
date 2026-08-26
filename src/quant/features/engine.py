"""Feature Engine (spec section 5): orchestrates per-symbol technical
features plus cross-sectional (momentum rank) and fundamental features into
one aligned feature table per symbol.

No look-ahead by construction: every technical feature is built from
`pandas.rolling`/`ewm` (non-centered) or `ta` indicators that only consume
rows up to and including the current one. See
`tests/features/test_no_lookahead.py` for a mechanical proof of this
property, run against every feature column this engine produces.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant import config
from quant.features import mean_reversion as mr
from quant.features import momentum as mom
from quant.features import price as price_feat
from quant.features import trend
from quant.features import volatility as vol
from quant.features import volume as volu

DEFAULT_RETURN_WINDOWS = (1, 5, 20, 60, 120, 252)


class FeatureEngine:
    def __init__(self, market: str):
        assert market in ("korea", "us")
        self.market = market

    def compute_technical_features(self, ohlcv: pd.DataFrame, benchmark_close: pd.Series | None = None) -> pd.DataFrame:
        """Compute the full technical feature set for one symbol's OHLCV
        history. `ohlcv` must have columns open/high/low/close/volume
        (adj_close optional, close is used throughout for consistency).
        """
        close, volume = ohlcv["close"], ohlcv["volume"]
        parts: list[pd.DataFrame | pd.Series] = []

        parts.append(price_feat.simple_returns(close, DEFAULT_RETURN_WINDOWS))

        for w in (20, 60, 120):
            parts.append(trend.sma(close, w))
        for w in (20, 60):
            parts.append(trend.ema(close, w))
        parts.append(trend.ma_distance(close, 20))
        parts.append(trend.ma_distance(close, 60))
        parts.append(trend.ma_cross(close, 20, 60))
        parts.append(trend.ma_cross(close, 50, 200))
        parts.append(trend.adx(ohlcv, 14))

        for w in (20, 60, 120):
            parts.append(mom.roc(close, w))
        parts.append(mom.rsi(close, 14))
        parts.append(mom.macd(close))
        if benchmark_close is not None:
            parts.append(mom.relative_strength(close, benchmark_close, 126))

        parts.append(vol.historical_volatility(close, 20))
        parts.append(vol.historical_volatility(close, 60))
        parts.append(vol.atr(ohlcv, 14))
        parts.append(vol.atr_pct(ohlcv, 14))
        parts.append(vol.bollinger_band_width(close, 20))
        parts.append(vol.downside_volatility(close, 20))

        parts.append(mr.zscore(close, 20))
        parts.append(mr.bollinger_position(close, 20))

        parts.append(volu.volume_ratio(volume, 20))
        parts.append(volu.volume_momentum(volume, 20))
        parts.append(volu.abnormal_volume(volume, 20))

        feat_df = pd.concat(parts, axis=1)
        return feat_df

    def compute_panel(
        self,
        ohlcv_map: dict[str, pd.DataFrame],
        benchmark_close: pd.Series | None = None,
    ) -> dict[str, pd.DataFrame]:
        return {
            sym: self.compute_technical_features(df, benchmark_close=benchmark_close)
            for sym, df in ohlcv_map.items()
            if df is not None and not df.empty
        }

    @staticmethod
    def cross_sectional_momentum_rank(
        feature_map: dict[str, pd.DataFrame], ret_col: str = "ret_120d"
    ) -> pd.DataFrame:
        """Wide (date x symbol) percentile rank of `ret_col` across the
        universe, using only symbols/dates that actually have data (a
        symbol not yet listed on a given date is simply NaN, not ranked)."""
        series = {}
        for sym, feat_df in feature_map.items():
            if ret_col in feat_df.columns:
                series[sym] = feat_df[ret_col]
        if not series:
            return pd.DataFrame()
        wide = pd.DataFrame(series)
        return mom.cross_sectional_momentum_rank(wide)

    @staticmethod
    def attach_momentum_rank(
        feature_map: dict[str, pd.DataFrame], rank_wide: pd.DataFrame, column_name: str = "momentum_rank"
    ) -> dict[str, pd.DataFrame]:
        out = {}
        for sym, feat_df in feature_map.items():
            if sym in rank_wide.columns:
                out[sym] = feat_df.assign(**{column_name: rank_wide[sym].reindex(feat_df.index)})
            else:
                out[sym] = feat_df.assign(**{column_name: pd.NA})
        return out

    # -- persistence --------------------------------------------------
    def _dir(self, base_dir: Path | None = None) -> Path:
        base = base_dir or config.resolve_path(config.settings()["paths"]["data_processed"])
        d = Path(base) / "features" / self.market
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, symbol: str, feat_df: pd.DataFrame, base_dir: Path | None = None) -> None:
        feat_df.to_parquet(self._dir(base_dir) / f"{symbol}.parquet")

    def load(self, symbol: str, base_dir: Path | None = None) -> pd.DataFrame | None:
        p = self._dir(base_dir) / f"{symbol}.parquet"
        return pd.read_parquet(p) if p.exists() else None
