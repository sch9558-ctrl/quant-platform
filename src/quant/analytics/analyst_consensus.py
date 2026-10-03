"""Analyst target-price accuracy and credibility analytics.

The core rule is temporal honesty: a report is not counted as a miss until
its evaluation horizon has actually elapsed. Reports that hit a target early
can be counted immediately; unresolved recent reports remain pending.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd

HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}
MIN_TIER_EVIDENCE = 5
FULL_CONFIDENCE_EVIDENCE = 20


@dataclass
class ReportEvaluation:
    source: str
    market: str
    symbol: str
    institution: str
    analyst: str | None
    published_at: str
    rating: str
    target_price: float | None
    start_price: float | None
    horizon: str
    hit: bool | None
    sessions_to_hit: int | None
    max_high: float | None
    min_low: float | None
    end_return_pct: float | None
    disparity_pct: float | None
    observed_sessions: int = 0
    matured: bool = False
    direction: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return asdict(self)


def _window(prices: pd.DataFrame | None, published_at, sessions: int):
    if prices is None or prices.empty:
        return None, None, False, 0
    p = prices.copy().sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(p.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    p.index = idx
    dt = pd.Timestamp(published_at)
    if dt.tzinfo is not None:
        dt = dt.tz_localize(None)
    eligible = p.loc[p.index >= dt.normalize()]
    if eligible.empty:
        return None, None, False, 0
    # +1 because the publication/start session is observation zero.
    need = sessions + 1
    window = eligible.iloc[:need]
    return eligible.iloc[0], window, len(eligible) >= need, len(window)


def _safe_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


class AnalystTracker:
    def evaluate_report(self, report, prices: pd.DataFrame) -> list[ReportEvaluation]:
        out: list[ReportEvaluation] = []
        for horizon, sessions in HORIZONS.items():
            first, window, matured, observed = _window(prices, report.published_at, sessions)
            start = (
                _safe_float(first.get("close"))
                if first is not None and pd.notna(first.get("close"))
                else None
            )
            target = _safe_float(report.target_price)
            hit = None
            days = None
            max_high = None
            min_low = None
            end_return = None
            disparity = None
            direction = "UNKNOWN"

            if window is not None and not window.empty and start is not None:
                high = pd.to_numeric(window["high"], errors="coerce")
                low = pd.to_numeric(window["low"], errors="coerce")
                close = pd.to_numeric(window["close"], errors="coerce")
                if high.notna().any():
                    max_high = float(high.max())
                if low.notna().any():
                    min_low = float(low.min())

                bearish = report.rating == "SELL" or (
                    target is not None and target > 0 and target < start
                )
                direction = "BEARISH" if bearish else "BULLISH"

                if matured and close.notna().any():
                    end_close = float(close.iloc[-1])
                    end_return = (end_close / start - 1) * 100

                if target is not None and target > 0:
                    mask = (low <= target) if bearish else (high >= target)
                    mask = mask.fillna(False)
                    if bool(mask.any()):
                        hit = True
                        days = int(np.flatnonzero(mask.to_numpy())[0])
                    elif matured:
                        # Only a completed horizon can be called a miss.
                        hit = False

                    # Full-horizon disparity is only final after maturity.
                    if matured:
                        if bearish and min_low is not None:
                            # Positive means the price never fell far enough.
                            disparity = (min_low - target) / target * 100
                        elif not bearish and max_high is not None:
                            # User-facing "hype gap": positive means target
                            # remained above the best realised price.
                            disparity = (target - max_high) / target * 100

            out.append(
                ReportEvaluation(
                    source=report.source,
                    market=report.market,
                    symbol=report.symbol,
                    institution=report.institution,
                    analyst=report.analyst,
                    published_at=str(pd.Timestamp(report.published_at).date()),
                    rating=report.rating,
                    target_price=target,
                    start_price=start,
                    horizon=horizon,
                    hit=hit,
                    sessions_to_hit=days,
                    max_high=max_high,
                    min_low=min_low,
                    end_return_pct=end_return,
                    disparity_pct=disparity,
                    observed_sessions=observed,
                    matured=matured,
                    direction=direction,
                )
            )
        return out

    @staticmethod
    def credibility(
        rows: Iterable[ReportEvaluation],
        horizon: str = "3m",
    ) -> dict:
        chosen = [r for r in rows if r.horizon == horizon]
        target_rows = [r for r in chosen if r.hit is not None]
        hit_rate = (
            float(np.mean([bool(r.hit) for r in target_rows]))
            if target_rows
            else 0.5
        )

        bearish = [
            r
            for r in chosen
            if r.end_return_pct is not None and r.direction == "BEARISH"
        ]
        downside = (
            float(np.mean([r.end_return_pct < 0 for r in bearish]))
            if bearish
            else 0.5
        )

        disparities = [
            abs(float(r.disparity_pct))
            for r in target_rows
            if r.disparity_pct is not None
        ]
        stability = (
            max(0.0, 1 - float(np.median(disparities)) / 100)
            if disparities
            else 0.5
        )

        raw_score = (hit_rate * 0.5 + downside * 0.2 + stability * 0.3) * 100
        # A single lucky call should never become an S-tier analyst. Shrink
        # sparse evidence toward a neutral 50 until enough matured reports exist.
        evidence_rows = [
            r for r in chosen if r.hit is not None or r.end_return_pct is not None
        ]
        evidence_n = len(evidence_rows)
        confidence = min(1.0, evidence_n / FULL_CONFIDENCE_EVIDENCE)
        score = 50 + (raw_score - 50) * confidence
        score = round(min(max(score, 0.0), 100.0), 2)

        if evidence_n < MIN_TIER_EVIDENCE:
            tier = "관찰중"
        else:
            tier = "S" if score >= 85 else "A" if score >= 70 else "B" if score >= 55 else "C"

        total_target_reports = sum(
            1 for r in chosen if r.target_price is not None
        )
        pending_target_reports = sum(
            1 for r in chosen if r.target_price is not None and r.hit is None
        )
        return {
            "horizon": horizon,
            "n_reports": len(chosen),
            "n_evaluable": evidence_n,
            "n_target_reports": total_target_reports,
            "n_mature_target_reports": len(target_rows),
            "n_pending_target_reports": pending_target_reports,
            "hit_rate": round(hit_rate, 4) if target_rows else None,
            "downside_foresight": round(downside, 4) if bearish else None,
            "disparity_stability": round(stability, 4) if disparities else None,
            "raw_score": round(raw_score, 2),
            "sample_confidence": round(confidence, 4),
            "credibility_score": score,
            "tier": tier,
        }

    def aggregate(self, evaluations: Iterable[ReportEvaluation]) -> dict:
        rows = list(evaluations)
        firms: dict[str, list[ReportEvaluation]] = {}
        analysts: dict[str, list[ReportEvaluation]] = {}
        for row in rows:
            firms.setdefault(row.institution or "Unknown", []).append(row)
            if row.analyst:
                analysts.setdefault(row.analyst, []).append(row)
        institutions = [
            {"institution": name, **self.credibility(group)}
            for name, group in firms.items()
        ]
        analyst_rows = [
            {"analyst": name, **self.credibility(group)}
            for name, group in analysts.items()
        ]
        institutions.sort(
            key=lambda x: (-x["sample_confidence"], -x["credibility_score"], -x["n_evaluable"], x["institution"])
        )
        analyst_rows.sort(
            key=lambda x: (-x["sample_confidence"], -x["credibility_score"], -x["n_evaluable"], x["analyst"])
        )
        return {
            "overall": self.credibility(rows),
            "institutions": institutions,
            "analysts": analyst_rows,
        }
