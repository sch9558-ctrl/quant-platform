"""Institutional portfolio allocation with honest fallbacks.

Order of preference:
1) Black-Litterman when every candidate has a real positive market cap and
   at least one empirical historical-signal view is available.
2) HRP when return history is sufficient but a market-cap equilibrium prior
   cannot be justified.
3) Return None and let the caller use the legacy PortfolioConstructor.

This deliberately refuses to fabricate market-cap weights merely to make the
Black-Litterman code path run.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from quant.hrp_allocator import hrp_allocate
from quant.portfolio.constructor import (
    PortfolioAllocation,
    PortfolioConstraints,
    PortfolioItem,
)
from quant.portfolio_optimizer import BlackLittermanOptimizer


@dataclass(frozen=True)
class InstitutionalAllocationDiagnostics:
    method: str
    observations: int
    view_count: int
    prior_source: str


def _aligned_returns(
    items: list[PortfolioItem],
    ohlcv_map: dict[str, pd.DataFrame],
    *,
    lookback: int = 253,
    min_observations: int = 60,
) -> pd.DataFrame:
    cols = {}
    for item in items:
        df = ohlcv_map.get(item.symbol)
        if df is None or df.empty or "close" not in df:
            continue
        close = pd.to_numeric(df["close"], errors="coerce").dropna().tail(lookback)
        ret = close.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
        if len(ret) >= min_observations:
            cols[item.symbol] = ret.rename(item.symbol)
    if len(cols) < 2:
        return pd.DataFrame()
    frame = pd.concat(cols.values(), axis=1, join="inner").dropna()
    return frame if len(frame) >= min_observations else pd.DataFrame()


def _empirical_views(
    symbols: list[str],
    signal_edges: dict[str, dict] | None,
) -> tuple[list[list[float]], list[float], list[float]]:
    edges = signal_edges or {}
    p_rows: list[list[float]] = []
    q: list[float] = []
    confidences: list[float] = []
    for idx, symbol in enumerate(symbols):
        edge = edges.get(symbol) or {}
        n = int(edge.get("n_obs") or 0)
        mean_20d = edge.get("mean_fwd_return")
        if n < 5 or mean_20d is None:
            continue
        try:
            mean_20d = float(mean_20d)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mean_20d):
            continue
        row = [0.0] * len(symbols)
        row[idx] = 1.0
        p_rows.append(row)
        # Convert the empirical 20-session edge into a conservative annual
        # simple-return view; clipping prevents one noisy edge from dominating.
        q.append(max(-0.50, min(1.00, mean_20d * (252.0 / 20.0))))
        confidences.append(min(0.90, 0.50 + min(n, 80) / 200.0))
    return p_rows, q, confidences


def _finalize(
    raw_weights: pd.Series,
    items: list[PortfolioItem],
    method_note: str,
    constraints: PortfolioConstraints,
) -> PortfolioAllocation:
    symbols = [i.symbol for i in items]
    w = raw_weights.reindex(symbols).fillna(0.0).clip(lower=0.0)
    notes = [method_note]

    if (w > constraints.max_position_weight).any():
        w = w.clip(upper=constraints.max_position_weight)
        notes.append("position weight cap applied")

    def _apply_group_cap(group_of: dict[str, str | None], cap: float, label: str) -> None:
        nonlocal w
        if cap <= 0:
            return
        groups = sorted({g for g in group_of.values() if g is not None})
        for group in groups:
            members = [s for s in w.index if group_of.get(s) == group]
            total = float(w.loc[members].sum()) if members else 0.0
            if total > cap:
                w.loc[members] *= cap / total
                notes.append(f"{label} weight cap applied")

    _apply_group_cap({i.symbol: i.sector for i in items}, constraints.max_sector_weight, "sector")
    _apply_group_cap({i.symbol: i.strategy_id for i in items}, constraints.max_strategy_weight, "strategy")
    _apply_group_cap({i.symbol: i.market for i in items}, constraints.max_market_weight, "market")

    max_invested = min(
        constraints.max_gross_exposure,
        1.0 - constraints.min_cash_weight,
    )
    if w.sum() > max_invested and w.sum() > 0:
        w *= max_invested / w.sum()
        notes.append("scaled down to respect gross/cash/market exposure caps")

    invested = float(w.sum())
    by_market: dict[str, float] = {}
    by_strategy: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    for item in items:
        wi = float(w.get(item.symbol, 0.0))
        by_market[item.market] = by_market.get(item.market, 0.0) + wi
        by_strategy[item.strategy_id] = by_strategy.get(item.strategy_id, 0.0) + wi
        if item.sector:
            by_sector[item.sector] = by_sector.get(item.sector, 0.0) + wi
    return PortfolioAllocation(
        weights=w,
        cash_weight=float(max(0.0, 1.0 - invested)),
        by_market=by_market,
        by_strategy=by_strategy,
        by_sector=by_sector,
        notes=notes,
    )


def build_institutional_allocation(
    items: list[PortfolioItem],
    ohlcv_map: dict[str, pd.DataFrame],
    *,
    market_caps: dict[str, float | None] | None = None,
    signal_edges: dict[str, dict] | None = None,
    constraints: PortfolioConstraints | None = None,
) -> tuple[PortfolioAllocation | None, InstitutionalAllocationDiagnostics | None]:
    if not items:
        return PortfolioAllocation(weights=pd.Series(dtype=float), cash_weight=1.0), (
            InstitutionalAllocationDiagnostics("cash", 0, 0, "none")
        )

    constraints = constraints or PortfolioConstraints.from_config()
    returns = _aligned_returns(items, ohlcv_map)
    if returns.empty or returns.shape[1] < 2:
        return None, None

    symbols = list(returns.columns)
    hrp = hrp_allocate(returns)
    caps = market_caps or {}
    usable_caps = {
        s: float(caps[s])
        for s in symbols
        if caps.get(s) is not None and float(caps[s]) > 0
    }
    p_rows, q, confidences = _empirical_views(symbols, signal_edges)

    if len(usable_caps) == len(symbols) and p_rows:
        cov = returns.cov() * 252.0
        market_weights = pd.Series(usable_caps, dtype=float)
        market_weights /= market_weights.sum()
        optimizer = BlackLittermanOptimizer(
            max_weight=constraints.max_position_weight,
        )
        posterior = optimizer.posterior(
            cov,
            market_weights,
            p_rows,
            q,
            confidences=confidences,
        )
        result = optimizer.optimize(
            posterior.expected_returns,
            posterior.covariance,
            initial_weights=hrp.weights,
        )
        if result.success:
            allocation = _finalize(
                result.weights,
                items,
                "institutional allocator: black_litterman",
                constraints,
            )
            return allocation, InstitutionalAllocationDiagnostics(
                "black_litterman", len(returns), len(p_rows), "market_cap"
            )

    allocation = _finalize(
        hrp.weights,
        items,
        "institutional allocator: hrp",
        constraints,
    )
    prior_source = "missing_market_cap" if len(usable_caps) != len(symbols) else "no_empirical_views"
    return allocation, InstitutionalAllocationDiagnostics(
        "hrp", len(returns), len(p_rows), prior_source
    )
