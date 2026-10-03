"""Execution-oriented ATR stops and account-risk position sizing."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PositionPlan:
    atr14: float
    stop_price: float
    risk_per_share: float
    quantity: int
    notional: float
    portfolio_weight: float
    max_weight: float


class TradeRiskManager:
    def __init__(self, account_risk_pct: float = 0.01, max_position_pct: float = 0.10, atr_multiple: float = 2.0):
        self.account_risk_pct = float(account_risk_pct)
        self.max_position_pct = float(max_position_pct)
        self.atr_multiple = float(atr_multiple)

    @staticmethod
    def atr(price_df: pd.DataFrame, period: int = 14) -> float:
        if price_df is None or len(price_df) < 2:
            raise ValueError("at least two price rows are required")
        high = pd.to_numeric(price_df["high"], errors="coerce")
        low = pd.to_numeric(price_df["low"], errors="coerce")
        close = pd.to_numeric(price_df["close"], errors="coerce")
        prev = close.shift(1)
        tr = pd.concat([(high-low).abs(), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
        value = tr.rolling(period, min_periods=min(period, len(tr))).mean().iloc[-1]
        if pd.isna(value) or value <= 0:
            raise ValueError("ATR could not be computed")
        return float(value)

    def build_plan(self, price_df: pd.DataFrame, portfolio_value: float, entry_price: float | None = None) -> PositionPlan:
        if portfolio_value <= 0:
            raise ValueError("portfolio_value must be positive")
        entry = float(entry_price if entry_price is not None else price_df["close"].iloc[-1])
        atr14 = self.atr(price_df, 14)
        stop = max(0.01, entry - self.atr_multiple * atr14)
        risk_per_share = max(entry - stop, 1e-9)
        risk_budget = portfolio_value * self.account_risk_pct
        by_risk = int(np.floor(risk_budget / risk_per_share))
        by_weight = int(np.floor((portfolio_value * self.max_position_pct) / entry))
        qty = max(0, min(by_risk, by_weight))
        notional = qty * entry
        return PositionPlan(
            atr14=atr14,
            stop_price=float(stop),
            risk_per_share=float(risk_per_share),
            quantity=qty,
            notional=float(notional),
            portfolio_weight=float(notional/portfolio_value),
            max_weight=self.max_position_pct,
        )

    @staticmethod
    def sector_capacity(existing_weights: dict[str,float], target_sector: str, proposed_weight: float, max_sector_weight: float = 0.30) -> bool:
        current = float(existing_weights.get(target_sector, 0.0))
        return current + float(proposed_weight) <= float(max_sector_weight) + 1e-12

    @staticmethod
    def position_count_allowed(current_positions: int, max_positions: int = 12) -> bool:
        return int(current_positions) < int(max_positions)
