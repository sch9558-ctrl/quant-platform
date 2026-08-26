"""Backtesting engine (spec section 9).

Simulates a strategy's `generate_weights` output as a sequence of realistic,
cost-aware trades:
  - a `fill_delay_bars`-day delay between the day a signal is decided (using
    only data available up to that day's close) and the day it is acted on,
  - a per-symbol commission + tax/fee + slippage cost model (`backtest.costs`),
  - a per-day, per-symbol cap on how much of the day's traded dollar volume a
    single rebalance may consume (`max_participation_of_volume`), so a
    strategy cannot conjure liquidity that wasn't there,
  - dividends and splits are captured implicitly by using `adj_close` (both
    real providers and the synthetic provider expose it) rather than raw
    `close` for return calculations -- this is the standard "total return"
    convention and avoids having to model corporate actions explicitly.

No look-ahead / survivorship bias: the engine only ever consumes
`strategy.generate_weights(...)`'s output, which is itself computed causally
(see strategy/base.py), and it only ever reads `ohlcv_map` -- if you pass in
a *point-in-time* universe/OHLCV map (i.e. the set of symbols that actually
existed as of a given historical date, not survivors filtered from today's
list), the backtest is free of survivorship bias by construction. Whether
that's true is the caller's responsibility (see universe/engine.py's
point-in-time snapshots and pipeline/research_pipeline.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.backtest.costs import CostModel
from quant.strategy.base import BaseStrategy

DEFAULT_INITIAL_CAPITAL = {"korea": 100_000_000.0, "us": 100_000.0}


@dataclass
class Trade:
    date: pd.Timestamp
    symbol: str
    side: str          # "buy" | "sell"
    weight_delta: float
    notional: float
    cost: float


@dataclass
class BacktestResult:
    market: str
    strategy_id: str
    params: dict
    start: pd.Timestamp
    end: pd.Timestamp
    initial_capital: float
    equity_curve: pd.Series
    daily_returns: pd.Series
    weights: pd.DataFrame          # actually-held weights each day (post-cap)
    target_weights: pd.DataFrame   # strategy's raw intended weights (pre-lag/cap)
    trades: list[Trade]
    turnover: pd.Series
    total_cost: float = field(init=False)

    def __post_init__(self):
        self.total_cost = sum(t.cost for t in self.trades)


class Backtester:
    def __init__(self, market: str, initial_capital: float | None = None):
        assert market in ("korea", "us")
        self.market = market
        self.cost_model = CostModel(market)
        self.initial_capital = initial_capital or DEFAULT_INITIAL_CAPITAL[market]

    def run(
        self,
        strategy: BaseStrategy,
        ohlcv_map: dict[str, pd.DataFrame],
        feature_map: dict[str, pd.DataFrame] | None = None,
        benchmark_close: pd.Series | None = None,
        symbol_meta: dict[str, dict] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> BacktestResult:
        symbol_meta = symbol_meta or {}
        raw_weights = strategy.generate_weights(ohlcv_map, feature_map=feature_map, benchmark_close=benchmark_close)

        if raw_weights is None or raw_weights.empty:
            empty_idx = pd.DatetimeIndex([])
            return BacktestResult(
                market=self.market, strategy_id=getattr(strategy, "id", "unknown"), params=strategy.params,
                start=pd.Timestamp(start) if start else pd.NaT, end=pd.Timestamp(end) if end else pd.NaT,
                initial_capital=self.initial_capital,
                equity_curve=pd.Series(dtype=float), daily_returns=pd.Series(dtype=float),
                weights=pd.DataFrame(), target_weights=pd.DataFrame(), trades=[],
                turnover=pd.Series(dtype=float),
            )

        if start:
            raw_weights = raw_weights.loc[pd.Timestamp(start):]
        if end:
            raw_weights = raw_weights.loc[:pd.Timestamp(end)]

        symbols = list(raw_weights.columns)
        dates = raw_weights.index

        # -- row-normalize: never let intended exposure exceed 100% ----------
        row_sum = raw_weights.sum(axis=1)
        scale = np.where(row_sum.to_numpy() > 1.0, 1.0 / row_sum.replace(0, np.nan).to_numpy(), 1.0)
        scale = np.nan_to_num(scale, nan=1.0)
        normalized = raw_weights.mul(scale, axis=0)

        # -- lag by the configured fill delay (signal decided at close of t,
        #    acted on at t + fill_delay_bars) --------------------------------
        fill_delay = self.cost_model.fill_delay_bars()
        target = normalized.shift(fill_delay).fillna(0.0)

        close_wide = pd.DataFrame({s: ohlcv_map[s]["adj_close"] for s in symbols if s in ohlcv_map}).reindex(dates)
        volume_wide = pd.DataFrame({s: ohlcv_map[s]["volume"] for s in symbols if s in ohlcv_map}).reindex(dates)
        raw_close_wide = pd.DataFrame({s: ohlcv_map[s]["close"] for s in symbols if s in ohlcv_map}).reindex(dates)
        returns_wide = close_wide.pct_change().fillna(0.0)

        max_participation = self.cost_model.max_participation_of_volume()
        buy_rate = {s: self.cost_model.apply(1.0, False, symbol_meta.get(s, {}).get("asset_type", "equity"),
                                              symbol_meta.get(s, {}).get("exchange")).total_cost for s in symbols}
        sell_rate = {s: self.cost_model.apply(1.0, True, symbol_meta.get(s, {}).get("asset_type", "equity"),
                                               symbol_meta.get(s, {}).get("exchange")).total_cost for s in symbols}

        nav = self.initial_capital
        nav_series = []
        held = pd.Series(0.0, index=symbols)
        weights_history = []
        trades: list[Trade] = []

        for t, date in enumerate(dates):
            target_t = target.iloc[t]
            delta = (target_t - held).fillna(0.0)

            price_t = raw_close_wide.iloc[t] if t < len(raw_close_wide) else pd.Series(dtype=float)
            vol_t = volume_wide.iloc[t] if t < len(volume_wide) else pd.Series(dtype=float)

            for sym in symbols:
                d = delta.get(sym, 0.0)
                if d == 0.0 or nav <= 0:
                    continue
                p, v = price_t.get(sym), vol_t.get(sym)
                if pd.notna(p) and pd.notna(v) and p > 0:
                    max_notional = v * p * max_participation
                    requested_notional = abs(d) * nav
                    if requested_notional > max_notional > 0:
                        capped_notional = max_notional
                        d = np.sign(d) * (capped_notional / nav)
                        delta[sym] = d

            new_held = (held + delta).clip(lower=0.0)

            day_cost = 0.0
            for sym in symbols:
                d = delta.get(sym, 0.0)
                if d == 0.0:
                    continue
                notional = abs(d) * nav
                rate = buy_rate[sym] if d > 0 else sell_rate[sym]
                cost = notional * rate
                day_cost += cost
                trades.append(Trade(
                    date=date, symbol=sym, side="buy" if d > 0 else "sell",
                    weight_delta=float(d), notional=float(notional), cost=float(cost),
                ))

            gross_return = float((new_held * returns_wide.iloc[t].reindex(symbols).fillna(0.0)).sum())
            nav = nav * (1 + gross_return) - day_cost

            held = new_held
            weights_history.append(held.copy())
            nav_series.append(nav)

        equity_curve = pd.Series(nav_series, index=dates, name="equity")
        weights_df = pd.DataFrame(weights_history, index=dates)
        daily_returns = equity_curve.pct_change().fillna(0.0)
        turnover = weights_df.diff().abs().sum(axis=1).fillna(weights_df.iloc[0].sum() if len(weights_df) else 0.0)

        return BacktestResult(
            market=self.market, strategy_id=getattr(strategy, "id", "unknown"), params=strategy.params,
            start=dates.min(), end=dates.max(), initial_capital=self.initial_capital,
            equity_curve=equity_curve, daily_returns=daily_returns,
            weights=weights_df, target_weights=raw_weights, trades=trades, turnover=turnover,
        )
