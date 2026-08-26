"""Benchmark comparison (spec section 11): is the strategy actually adding
value, or just riding a rising market? Every strategy backtest should be
compared against a simple buy & hold of the relevant index/ETF.
"""
from __future__ import annotations

import pandas as pd

from quant.analytics.metrics import PerformanceMetrics, compute_metrics


def buy_and_hold_equity_curve(index_ohlcv: pd.DataFrame, initial_capital: float) -> pd.Series:
    price_col = "adj_close" if "adj_close" in index_ohlcv.columns else "close"
    close = index_ohlcv[price_col].dropna()
    if close.empty:
        return pd.Series(dtype=float)
    return (initial_capital * close / close.iloc[0]).rename("benchmark_equity")


def compare_to_benchmark(
    strategy_equity: pd.Series,
    strategy_returns: pd.Series,
    benchmark_ohlcv: pd.DataFrame,
    initial_capital: float,
) -> dict:
    bench_equity_full = buy_and_hold_equity_curve(benchmark_ohlcv, initial_capital)
    bench_equity = bench_equity_full.reindex(strategy_equity.index).ffill().bfill()
    bench_returns = bench_equity.pct_change().fillna(0.0)

    strategy_metrics: PerformanceMetrics = compute_metrics(
        strategy_equity, strategy_returns, benchmark_close=bench_equity,
    )
    benchmark_metrics: PerformanceMetrics = compute_metrics(bench_equity, bench_returns)

    return {
        "strategy_metrics": strategy_metrics,
        "benchmark_metrics": benchmark_metrics,
        "benchmark_equity": bench_equity,
        "excess_total_return": strategy_metrics.total_return - benchmark_metrics.total_return,
        "excess_cagr": strategy_metrics.cagr - benchmark_metrics.cagr,
    }
