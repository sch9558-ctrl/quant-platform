"""Screening + candidate scoring (spec section 2, "Daily Market Scanner").

Turns per-symbol technical/fundamental features into a scored, ranked
candidate list, with every sub-score shown (not just a single opaque
number) so a human can see *why* a name is a candidate:
  price, recent return, momentum rank, trend score, volume score,
  volatility, relative strength, a discrete "signal" label, an estimated
  transaction cost, an empirical "similar historical signal" edge, a risk
  score, and the final composite score.

This module assumes the Universe Engine has already excluded illiquid /
low-cap / halted names -- it operates on the symbols FeatureEngine computed
features for, which should already be `UniverseSnapshot.included_symbols()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant import config
from quant.backtest.costs import CostModel


@dataclass
class CandidateResult:
    symbol: str
    name: str
    market: str
    exchange: str
    asset_type: str
    price: float
    recent_return_20d: float | None
    momentum_rank: float | None
    trend_score: float | None
    volume_score: float | None
    volatility: float | None
    relative_strength: float | None
    fundamental_score: float | None
    signal: str
    expected_cost_bps: float
    historical_signal_edge: dict
    risk_score: float
    composite_score: float
    sub_scores: dict = field(default_factory=dict)


def _safe_last(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    val = series.dropna()
    return float(val.iloc[-1]) if len(val) else None


def historical_signal_edge(
    feat_df: pd.DataFrame,
    close: pd.Series,
    signal_col: str = "momentum_rank",
    threshold: float = 0.8,
    forward_window: int = 20,
) -> dict:
    """Empirical, causally-computed track record of "what happened after
    similar signals fired historically" for this symbol. Only uses
    already-realized forward returns (i.e. it never looks at the most
    recent `forward_window` bars' outcome, since those aren't known yet at
    the current date), so displaying this alongside today's live signal
    does not leak information about today's outcome.
    """
    if signal_col not in feat_df.columns or len(close) < forward_window + 5:
        return {"n_obs": 0, "mean_fwd_return": None, "win_rate": None}

    aligned_signal = feat_df[signal_col].reindex(close.index)
    fwd_ret = close.shift(-forward_window) / close - 1
    valid = fwd_ret.notna()  # excludes the most recent `forward_window` bars automatically
    hit = aligned_signal >= threshold
    mask = valid & hit.fillna(False)
    obs = fwd_ret[mask]

    if len(obs) < 5:
        return {"n_obs": int(len(obs)), "mean_fwd_return": None, "win_rate": None}
    return {
        "n_obs": int(len(obs)),
        "mean_fwd_return": float(obs.mean()),
        "win_rate": float((obs > 0).mean()),
    }


def _trend_score(feat_row: pd.Series) -> float | None:
    parts = []
    for col, weight in (("ma_dist_20", 1.0), ("ma_cross_signal_20_60", 0.5), ("adx_14", 0.5)):
        if col in feat_row and pd.notna(feat_row[col]):
            v = feat_row[col]
            if col == "adx_14":
                v = min(v, 50) / 50  # normalize ADX (trend strength, not direction) to ~[0,1]
            parts.append(np.tanh(v) * weight if col != "adx_14" else v * weight)
    if not parts:
        return None
    return float(np.clip(sum(parts) / sum(w for _, w in (("a", 1.0), ("b", 0.5), ("c", 0.5))), -1, 1))


def _volume_score(feat_row: pd.Series) -> float | None:
    vals = [feat_row.get(c) for c in ("vol_ratio_20", "abn_vol_20") if pd.notna(feat_row.get(c, np.nan))]
    if not vals:
        return None
    ratio = feat_row.get("vol_ratio_20", 1.0)
    abn = feat_row.get("abn_vol_20", 0.0)
    return float(np.tanh((ratio - 1) + 0.3 * abn))


def _mean_reversion_score(feat_row: pd.Series) -> float | None:
    z = feat_row.get("zscore_20")
    if pd.isna(z):
        return None
    # oversold (very negative z) -> positive mean-reversion opportunity score
    return float(np.clip(-z / 2, -1, 1))


def _derive_signal_label(trend_s, mom_rank, mr_s, vol_score, vol_ratio) -> str:
    labels = []
    if trend_s is not None and trend_s > 0.3:
        labels.append("trend_up")
    elif trend_s is not None and trend_s < -0.3:
        labels.append("trend_down")
    if mom_rank is not None and mom_rank >= 0.8:
        labels.append("momentum_top_quintile")
    if mr_s is not None and mr_s > 0.5:
        labels.append("oversold_reversion")
    if vol_ratio is not None and vol_ratio >= 2.0:
        labels.append("volume_breakout")
    return "+".join(labels) if labels else "neutral"


def score_candidates(
    market: str,
    feature_map: dict[str, pd.DataFrame],
    ohlcv_map: dict[str, pd.DataFrame],
    symbol_meta: dict[str, dict],
    fundamental_scores: pd.DataFrame | None = None,
) -> list[CandidateResult]:
    """symbol_meta[symbol] should have at least: name, exchange, asset_type."""
    cfg = config.ranking_config()["candidate_score_weights"]
    cost_model = CostModel(market)

    results: list[CandidateResult] = []
    for symbol, feat_df in feature_map.items():
        if feat_df is None or feat_df.empty:
            continue
        row = feat_df.iloc[-1]
        close = ohlcv_map.get(symbol, pd.DataFrame()).get("close", pd.Series(dtype=float))
        price = _safe_last(close)
        if price is None:
            continue

        meta = symbol_meta.get(symbol, {})
        recent_return = row.get("ret_20d")
        momentum_rank = row.get("momentum_rank")
        trend_s = _trend_score(row)
        volume_s = _volume_score(row)
        mr_s = _mean_reversion_score(row)
        volatility = row.get("hvol_20")
        rel_strength = row.get("rel_strength_126")
        fundamental_s = None
        if fundamental_scores is not None and symbol in fundamental_scores.index:
            fundamental_s = float(fundamental_scores.loc[symbol].mean())

        risk_score = None
        if pd.notna(volatility):
            downside = row.get("downside_vol_20", volatility)
            risk_score = float(np.clip((volatility * 0.6 + downside * 0.4) / 0.6, 0, 2) / 2)  # ~[0,1]

        sub = {
            "momentum": momentum_rank if pd.notna(momentum_rank) else 0.5,
            "trend": (trend_s + 1) / 2 if trend_s is not None else 0.5,
            "volume": (volume_s + 1) / 2 if volume_s is not None else 0.5,
            "mean_reversion": (mr_s + 1) / 2 if mr_s is not None else 0.5,
            "volatility_penalty": 1 - (risk_score if risk_score is not None else 0.5),
            "relative_strength": (np.tanh(rel_strength) + 1) / 2 if pd.notna(rel_strength) else 0.5,
            "fundamental": (fundamental_s / 4 + 0.5) if fundamental_s is not None else 0.5,
            "risk_penalty": 1 - (risk_score if risk_score is not None else 0.5),
        }
        composite = sum(cfg.get(k, 0) * v for k, v in sub.items())

        edge = historical_signal_edge(feat_df, close)

        results.append(CandidateResult(
            symbol=symbol, name=meta.get("name", symbol), market=market,
            exchange=meta.get("exchange", ""), asset_type=meta.get("asset_type", "equity"),
            price=price,
            recent_return_20d=float(recent_return) if pd.notna(recent_return) else None,
            momentum_rank=float(momentum_rank) if pd.notna(momentum_rank) else None,
            trend_score=trend_s, volume_score=volume_s,
            volatility=float(volatility) if pd.notna(volatility) else None,
            relative_strength=float(rel_strength) if pd.notna(rel_strength) else None,
            fundamental_score=fundamental_s,
            signal=_derive_signal_label(trend_s, momentum_rank, mr_s, volume_s, row.get("vol_ratio_20")),
            expected_cost_bps=cost_model.estimate_round_trip_cost_bps(
                meta.get("asset_type", "equity"), meta.get("exchange")
            ),
            historical_signal_edge=edge,
            risk_score=risk_score if risk_score is not None else 0.5,
            composite_score=float(composite),
            sub_scores=sub,
        ))

    results.sort(key=lambda r: r.composite_score, reverse=True)
    return results


def top_candidates(results: list[CandidateResult], n: int = 20) -> list[CandidateResult]:
    return results[:n]
