"""Market Regime Detection (spec section 4).

Classifies the current environment for a market's benchmark index along
three independent axes:
  - trend_regime:      "bull" | "bear" | "sideways"
  - volatility_regime: "high_vol" | "low_vol" | "normal_vol"
  - risk_regime:       "risk_on" | "risk_off" | "neutral"

All inputs (`index_ohlcv`, and the OHLCV panel passed to `compute_breadth`)
are assumed to already be trimmed to <= `as_of`, consistent with the rest of
this codebase's causality convention -- this module does not itself slice
by date, it trusts the caller (see `pipeline/research_pipeline.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import config


@dataclass
class BreadthStats:
    advances: int
    declines: int
    adv_dec_ratio: float | None
    new_highs: int
    new_lows: int
    nh_nl_ratio: float | None


@dataclass
class RegimeResult:
    market: str
    as_of: pd.Timestamp
    trend_regime: str
    volatility_regime: str
    risk_regime: str
    index_return_6m: float | None
    index_vol_annualized: float | None
    volatility_percentile: float | None
    breadth: BreadthStats | None
    details: dict = field(default_factory=dict)

    def summary_label(self) -> str:
        """Compact human label, e.g. 'Bull / Low-Vol / Risk-On'."""
        t = {"bull": "Bull", "bear": "Bear", "sideways": "Sideways"}[self.trend_regime]
        v = {"high_vol": "High-Vol", "low_vol": "Low-Vol", "normal_vol": "Normal-Vol"}[self.volatility_regime]
        r = {"risk_on": "Risk-On", "risk_off": "Risk-Off", "neutral": "Neutral"}[self.risk_regime]
        return f"{t} / {v} / {r}"


def compute_breadth(ohlcv_map: dict[str, pd.DataFrame], lookback_new_high_low: int = 252) -> BreadthStats:
    advances = declines = new_highs = new_lows = 0
    for sym, df in ohlcv_map.items():
        if df is None or len(df) < 2:
            continue
        last, prev = df["close"].iloc[-1], df["close"].iloc[-2]
        if last > prev:
            advances += 1
        elif last < prev:
            declines += 1

        window = df["close"].tail(lookback_new_high_low)
        if len(window) >= 20:
            if last >= window.max():
                new_highs += 1
            if last <= window.min():
                new_lows += 1

    total_ad = advances + declines
    total_nhnl = new_highs + new_lows
    return BreadthStats(
        advances=advances, declines=declines,
        adv_dec_ratio=(advances / total_ad) if total_ad > 0 else None,
        new_highs=new_highs, new_lows=new_lows,
        nh_nl_ratio=(new_highs / total_nhnl) if total_nhnl > 0 else None,
    )


class RegimeDetector:
    def __init__(self, market: str):
        assert market in ("korea", "us")
        self.market = market
        self.cfg = config.regime_config()

    def detect(
        self,
        index_ohlcv: pd.DataFrame,
        breadth: BreadthStats | None = None,
    ) -> RegimeResult:
        cfg = self.cfg
        close = index_ohlcv["close"].dropna()
        as_of = close.index[-1] if len(close) else pd.Timestamp.today()

        fast_w = cfg["trend"]["fast_ma"]
        slow_w = cfg["trend"]["slow_ma"]
        mom_lb = cfg["trend"]["momentum_lookback_days"]

        fast_ma = close.rolling(fast_w, min_periods=max(5, fast_w // 2)).mean()
        slow_ma = close.rolling(slow_w, min_periods=max(10, slow_w // 2)).mean()

        ret_6m = None
        if len(close) > mom_lb:
            ret_6m = float(close.iloc[-1] / close.iloc[-mom_lb - 1] - 1)

        vol_lb = cfg["volatility"]["lookback_days"]
        ann = cfg["volatility"]["annualization_factor"]
        vol_series = close.pct_change().rolling(vol_lb, min_periods=max(5, vol_lb // 2)).std() * np.sqrt(ann)
        vol_ann = float(vol_series.iloc[-1]) if len(vol_series.dropna()) else None
        vol_percentile = float(vol_series.rank(pct=True).iloc[-1]) if len(vol_series.dropna()) >= 5 else None

        trend_regime = self._classify_trend(close, fast_ma, slow_ma, ret_6m)
        volatility_regime = self._classify_volatility(vol_percentile)
        risk_regime = self._classify_risk(trend_regime, volatility_regime, vol_percentile, breadth)

        return RegimeResult(
            market=self.market, as_of=pd.Timestamp(as_of),
            trend_regime=trend_regime, volatility_regime=volatility_regime,
            risk_regime=risk_regime, index_return_6m=ret_6m,
            index_vol_annualized=vol_ann, volatility_percentile=vol_percentile,
            breadth=breadth,
            details={
                "fast_ma": float(fast_ma.iloc[-1]) if len(fast_ma.dropna()) else None,
                "slow_ma": float(slow_ma.iloc[-1]) if len(slow_ma.dropna()) else None,
                "close": float(close.iloc[-1]) if len(close) else None,
            },
        )

    def _classify_trend(self, close: pd.Series, fast_ma: pd.Series, slow_ma: pd.Series, ret_6m: float | None) -> str:
        cls = self.cfg["classification"]
        if ret_6m is None or pd.isna(slow_ma.iloc[-1]):
            return "sideways"

        # A small 6-month move is "sideways" regardless of exactly where
        # price sits relative to its moving averages -- noise around a flat
        # market can put price a hair above or below its MA either way, and
        # that should never flip the label to bull/bear on its own.
        if abs(ret_6m) <= cls["sideways_band"]:
            return "sideways"

        above_slow = close.iloc[-1] > slow_ma.iloc[-1]
        if ret_6m > 0:
            return "bull" if (ret_6m >= cls["bull_momentum_threshold"] or above_slow) else "sideways"
        return "bear" if (ret_6m <= cls["bear_momentum_threshold"] or not above_slow) else "sideways"

    def _classify_volatility(self, vol_percentile: float | None) -> str:
        if vol_percentile is None:
            return "normal_vol"
        v = self.cfg["volatility"]
        if vol_percentile >= v["high_vol_percentile"]:
            return "high_vol"
        if vol_percentile <= v["low_vol_percentile"]:
            return "low_vol"
        return "normal_vol"

    def _classify_risk(
        self, trend_regime: str, volatility_regime: str, vol_percentile: float | None, breadth: BreadthStats | None
    ) -> str:
        ro = self.cfg["risk_on_off"]
        risk_off_votes = 0
        risk_on_votes = 0

        if vol_percentile is not None and vol_percentile >= ro["risk_off_vol_percentile"]:
            risk_off_votes += 1
        elif volatility_regime == "low_vol":
            risk_on_votes += 1

        if breadth is not None and breadth.adv_dec_ratio is not None:
            if breadth.adv_dec_ratio < ro["risk_off_breadth_threshold"]:
                risk_off_votes += 1
            elif breadth.adv_dec_ratio > 0.5:
                risk_on_votes += 1

        if trend_regime == "bear":
            risk_off_votes += 1
        elif trend_regime == "bull":
            risk_on_votes += 1

        if risk_off_votes > risk_on_votes:
            return "risk_off"
        if risk_on_votes > risk_off_votes:
            return "risk_on"
        return "neutral"
