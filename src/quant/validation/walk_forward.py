"""Walk-Forward Analysis (spec section 10): repeatedly select parameters
using only in-sample + validation data, then evaluate on a completely
untouched out-of-sample window, roll the window forward, and repeat. The
chained out-of-sample equity curve across all folds is the single most
important number this whole platform produces (spec section 32: OOS
performance is priority #1, ahead of raw backtested return).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant.analytics.metrics import PerformanceMetrics, compute_metrics
from quant.backtest.engine import Backtester
from quant.strategy import registry
from quant.validation import splitter, stability


@dataclass
class FoldResult:
    fold: splitter.Fold
    chosen_params: dict
    is_metrics: PerformanceMetrics
    oos_metrics: PerformanceMetrics
    stability: stability.StabilityResult | None


@dataclass
class WalkForwardResult:
    strategy_id: str
    market: str
    fold_results: list[FoldResult]
    aggregate_oos_equity: pd.Series
    aggregate_oos_metrics: PerformanceMetrics


class WalkForwardAnalyzer:
    def __init__(self, market: str, initial_capital: float | None = None):
        self.market = market
        self.initial_capital = initial_capital

    def run(
        self,
        strategy_id: str,
        ohlcv_map: dict[str, pd.DataFrame],
        feature_map: dict[str, pd.DataFrame] | None = None,
        benchmark_close: pd.Series | None = None,
        symbol_meta: dict[str, dict] | None = None,
        start: str | None = None,
        end: str | None = None,
        use_param_search: bool = True,
    ) -> WalkForwardResult:
        all_dates = sorted({d for df in ohlcv_map.values() for d in df.index})
        if not all_dates:
            empty = pd.Series(dtype=float)
            return WalkForwardResult(strategy_id, self.market, [], empty, compute_metrics(empty, empty))

        start = start or all_dates[0].strftime("%Y-%m-%d")
        end = end or all_dates[-1].strftime("%Y-%m-%d")
        folds = splitter.get_folds(start, end)

        param_grid = registry.param_grid_for(strategy_id) if use_param_search else {}
        backtester = Backtester(self.market, self.initial_capital)
        running_capital = backtester.initial_capital

        fold_results: list[FoldResult] = []
        oos_equity_segments: list[pd.Series] = []

        for fold in folds:
            chosen_params: dict = {}
            stab_result = None

            if param_grid:
                def eval_fn(params: dict, fold=fold) -> float:
                    strat = registry.build_strategy(strategy_id, params)
                    probe_bt = Backtester(self.market, initial_capital=1.0)
                    res = probe_bt.run(
                        strat, ohlcv_map, feature_map, benchmark_close, symbol_meta,
                        start=fold.is_start.strftime("%Y-%m-%d"), end=fold.val_end.strftime("%Y-%m-%d"),
                    )
                    if res.equity_curve.empty:
                        return 0.0
                    return compute_metrics(res.equity_curve, res.daily_returns).sharpe

                eval_results = stability.evaluate_param_grid(param_grid, eval_fn)
                stab_result = stability.select_robust_params(eval_results)
                chosen_params = stab_result.params if stab_result else {}

            is_strategy = registry.build_strategy(strategy_id, chosen_params)
            is_probe_bt = Backtester(self.market, initial_capital=1.0)
            is_bt_result = is_probe_bt.run(
                is_strategy, ohlcv_map, feature_map, benchmark_close, symbol_meta,
                start=fold.is_start.strftime("%Y-%m-%d"), end=fold.val_end.strftime("%Y-%m-%d"),
            )
            is_metrics = compute_metrics(
                is_bt_result.equity_curve, is_bt_result.daily_returns, is_bt_result.weights,
                ohlcv_map, is_bt_result.turnover, benchmark_close,
            )

            oos_strategy = registry.build_strategy(strategy_id, chosen_params)
            oos_bt = Backtester(self.market, initial_capital=running_capital)
            oos_result = oos_bt.run(
                oos_strategy, ohlcv_map, feature_map, benchmark_close, symbol_meta,
                start=fold.oos_start.strftime("%Y-%m-%d"), end=fold.oos_end.strftime("%Y-%m-%d"),
            )
            oos_metrics = compute_metrics(
                oos_result.equity_curve, oos_result.daily_returns, oos_result.weights,
                ohlcv_map, oos_result.turnover, benchmark_close,
            )

            if not oos_result.equity_curve.empty:
                running_capital = float(oos_result.equity_curve.iloc[-1])
                oos_equity_segments.append(oos_result.equity_curve)

            fold_results.append(FoldResult(
                fold=fold, chosen_params=chosen_params, is_metrics=is_metrics,
                oos_metrics=oos_metrics, stability=stab_result,
            ))

        if oos_equity_segments:
            aggregate_oos_equity = pd.concat(oos_equity_segments)
            aggregate_oos_equity = aggregate_oos_equity[~aggregate_oos_equity.index.duplicated(keep="first")]
        else:
            aggregate_oos_equity = pd.Series(dtype=float)

        aggregate_oos_returns = aggregate_oos_equity.pct_change().fillna(0.0) if len(aggregate_oos_equity) else aggregate_oos_equity
        aggregate_metrics = compute_metrics(aggregate_oos_equity, aggregate_oos_returns, benchmark_close=benchmark_close)

        return WalkForwardResult(
            strategy_id=strategy_id, market=self.market, fold_results=fold_results,
            aggregate_oos_equity=aggregate_oos_equity, aggregate_oos_metrics=aggregate_metrics,
        )
