"""Analyst consensus target-price calibration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TradeSignal:
    decision: str
    upside: float
    downside: float
    risk_reward_ratio: float
    current_price: float
    calibrated_target: float
    support_level: float


class TargetPriceCalibrator:
    """Bias-correct analyst targets with realized price outcomes."""

    def __init__(self, lookback_years: int = 2, horizon_months: int = 3):
        self.lookback_years = int(lookback_years)
        self.horizon_months = int(horizon_months)

    @staticmethod
    def _field(obj, name, default=None):
        return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)

    def calculate_analyst_bias(self, analyst_id: str, historical_reports: Iterable, price_df: pd.DataFrame) -> float:
        """Mean target overshoot: (target - max future high) / target."""
        if price_df is None or price_df.empty:
            return 0.0
        prices = price_df.copy()
        if not isinstance(prices.index, pd.DatetimeIndex):
            if "date" not in prices.columns:
                return 0.0
            prices.index = pd.to_datetime(prices["date"])
        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        high_col = "high" if "high" in prices.columns else "close"
        highs = pd.to_numeric(prices[high_col], errors="coerce")
        cutoff = prices.index.max() - pd.DateOffset(years=self.lookback_years)
        obs = []
        for report in historical_reports:
            rid = self._field(report, "analyst_id") or self._field(report, "analyst") or self._field(report, "institution")
            if analyst_id and rid not in {None, analyst_id}:
                continue
            target = self._field(report, "target_price")
            published = self._field(report, "published_at")
            if target in (None, 0) or not published:
                continue
            target = float(target)
            start = pd.Timestamp(published).tz_localize(None)
            if start < cutoff:
                continue
            end = start + pd.DateOffset(months=self.horizon_months)
            window = highs.loc[(highs.index >= start) & (highs.index <= end)].dropna()
            if not window.empty:
                obs.append((target - float(window.max())) / target)
        return float(np.mean(obs)) if obs else 0.0

    @staticmethod
    def calibrate_target_price(raw_target: float, analyst_bias: float, market_regime_factor: float) -> float:
        if raw_target <= 0 or market_regime_factor <= 0:
            raise ValueError("raw_target and market_regime_factor must be positive")
        return float(raw_target) * max(0.0, 1.0 - max(0.0, float(analyst_bias))) * float(market_regime_factor)

    @staticmethod
    def generate_trade_signal(current_price: float, calibrated_target: float, support_level: float) -> TradeSignal:
        if min(current_price, calibrated_target, support_level) <= 0:
            raise ValueError("prices must be positive")
        upside = (calibrated_target - current_price) / current_price
        downside = max((current_price - support_level) / current_price, 1e-9)
        rr = upside / downside
        if current_price <= support_level:
            decision = "STOP_LOSS"
        elif current_price >= calibrated_target or upside < 0.05:
            decision = "SELL"
        elif upside >= 0.10 and rr >= 2.0:
            decision = "BUY"
        else:
            decision = "HOLD"
        return TradeSignal(decision, float(upside), float(downside), float(rr), float(current_price), float(calibrated_target), float(support_level))
