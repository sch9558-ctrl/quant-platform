"""Portfolio Construction (spec section 16).

Turns a list of "things we want to hold" (symbol + market + strategy +
sector + a raw sizing signal) into a single constrained weight vector:
apply one of several weighting schemes, then enforce per-position,
per-sector, per-strategy, per-market, and gross-exposure caps plus a
minimum cash floor via iterative proportional scaling.

Note on "risk parity": this implements the common simplified/"naive" risk
parity (weight inversely proportional to each position's own variance,
ignoring cross-asset correlation) rather than a full correlation-aware
optimization -- that is a reasonable, well-known approximation for a
personal research tool, and is called out here as an explicit extension
point (a proper risk-parity optimizer could replace `_risk_parity_weights`
without changing this class's interface).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant import config


@dataclass
class PortfolioItem:
    symbol: str
    market: str
    strategy_id: str
    sector: str | None = None
    signal_strength: float = 1.0    # e.g. composite candidate/strategy score, >= 0
    volatility: float | None = None  # annualized, used by volatility/inverse-vol/risk-parity weighting


@dataclass
class PortfolioConstraints:
    max_position_weight: float
    max_sector_weight: float
    max_strategy_weight: float
    max_market_weight: float
    min_cash_weight: float
    max_gross_exposure: float

    @classmethod
    def from_config(cls) -> "PortfolioConstraints":
        c = config.portfolio_config()["constraints"]
        return cls(**c)


@dataclass
class PortfolioAllocation:
    weights: pd.Series                  # symbol -> final weight (post-constraints)
    cash_weight: float
    by_market: dict[str, float] = field(default_factory=dict)
    by_strategy: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class PortfolioConstructor:
    def __init__(self, method: str | None = None, constraints: PortfolioConstraints | None = None):
        cfg = config.portfolio_config()
        self.method = method or cfg["weighting"]["method"]
        self.constraints = constraints or PortfolioConstraints.from_config()

    def _raw_weights(self, items: list[PortfolioItem]) -> pd.Series:
        idx = [i.symbol for i in items]
        if self.method == "equal_weight":
            w = pd.Series(1.0, index=idx)
        elif self.method == "signal_weight":
            w = pd.Series([max(i.signal_strength, 0.0) for i in items], index=idx)
        elif self.method == "volatility_weight":
            w = pd.Series([i.volatility or 0.0 for i in items], index=idx)
        elif self.method == "inverse_volatility":
            w = pd.Series([1.0 / i.volatility if i.volatility else 0.0 for i in items], index=idx)
        elif self.method == "risk_parity":
            w = pd.Series([1.0 / (i.volatility ** 2) if i.volatility else 0.0 for i in items], index=idx)
        else:
            raise ValueError(f"Unknown weighting method: {self.method}")

        total = w.sum()
        if total <= 0:
            return pd.Series(1.0 / len(items), index=idx) if items else pd.Series(dtype=float)
        return w / total

    @staticmethod
    def _apply_group_cap(weights: pd.Series, group_of: dict[str, str | None], cap: float) -> tuple[pd.Series, bool]:
        w = weights.copy()
        grouped = pd.Series({sym: group_of.get(sym) for sym in w.index})
        changed = False
        for group_name in grouped.dropna().unique():
            members = grouped[grouped == group_name].index
            group_sum = w.loc[members].sum()
            if group_sum > cap > 0:
                w.loc[members] = w.loc[members] * (cap / group_sum)
                changed = True
        return w, changed

    def compute_weights(self, items: list[PortfolioItem]) -> PortfolioAllocation:
        if not items:
            return PortfolioAllocation(weights=pd.Series(dtype=float), cash_weight=1.0)

        w = self._raw_weights(items)
        notes: list[str] = []

        if (w > self.constraints.max_position_weight).any():
            w = w.clip(upper=self.constraints.max_position_weight)
            notes.append("position weight cap applied")

        sector_of = {i.symbol: i.sector for i in items}
        strategy_of = {i.symbol: i.strategy_id for i in items}
        market_of = {i.symbol: i.market for i in items}

        for _ in range(5):
            any_changed = False
            for group_of, cap, label in (
                (sector_of, self.constraints.max_sector_weight, "sector"),
                (strategy_of, self.constraints.max_strategy_weight, "strategy"),
                (market_of, self.constraints.max_market_weight, "market"),
            ):
                w, changed = self._apply_group_cap(w, group_of, cap)
                if changed:
                    any_changed = True
                    notes.append(f"{label} weight cap applied")
            if not any_changed:
                break

        max_invested = min(self.constraints.max_gross_exposure, 1 - self.constraints.min_cash_weight)
        total_invested = w.sum()
        if total_invested > max_invested and total_invested > 0:
            w = w * (max_invested / total_invested)
            notes.append("scaled down to respect gross exposure / minimum cash floor")

        cash_weight = 1 - w.sum()

        by_market: dict[str, float] = {}
        by_strategy: dict[str, float] = {}
        by_sector: dict[str, float] = {}
        for i in items:
            wi = float(w.get(i.symbol, 0.0))
            by_market[i.market] = by_market.get(i.market, 0.0) + wi
            by_strategy[i.strategy_id] = by_strategy.get(i.strategy_id, 0.0) + wi
            if i.sector:
                by_sector[i.sector] = by_sector.get(i.sector, 0.0) + wi

        return PortfolioAllocation(
            weights=w, cash_weight=cash_weight, by_market=by_market,
            by_strategy=by_strategy, by_sector=by_sector, notes=notes,
        )
