"""Visualization (spec section 21). Every function returns a matplotlib
`Figure` (never calls plt.show()) so callers (CLI, report generator,
Streamlit dashboard) decide whether to save it, embed it, or display it.
Uses the non-interactive "Agg" backend so this works in headless/server
environments (cron jobs, this sandbox, CI).
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant.analytics.metrics import drawdown_series

_FIGSIZE = (10, 5)


def plot_equity_curve(equity: pd.Series, benchmark_equity: pd.Series | None = None, title: str = "Equity Curve") -> plt.Figure:
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(equity.index, equity.values, label="Strategy", linewidth=1.5)
    if benchmark_equity is not None and not benchmark_equity.empty:
        ax.plot(benchmark_equity.index, benchmark_equity.values, label="Benchmark", linewidth=1.2, linestyle="--")
    ax.set_title(title)
    ax.set_ylabel("Portfolio Value")
    ax.legend()
    fig.tight_layout()
    return fig


def plot_drawdown(equity: pd.Series, title: str = "Drawdown") -> plt.Figure:
    dd = drawdown_series(equity)
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.fill_between(dd.index, dd.values * 100, 0, color="firebrick", alpha=0.4)
    ax.plot(dd.index, dd.values * 100, color="firebrick", linewidth=1)
    ax.set_title(title)
    ax.set_ylabel("Drawdown (%)")
    fig.tight_layout()
    return fig


def plot_rolling_sharpe(daily_returns: pd.Series, window: int = 126, title: str = "Rolling Sharpe") -> plt.Figure:
    roll_mean = daily_returns.rolling(window).mean()
    roll_std = daily_returns.rolling(window).std()
    rolling_sharpe = (roll_mean / roll_std) * np.sqrt(252)
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(rolling_sharpe.index, rolling_sharpe.values)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title(f"{title} ({window}d)")
    fig.tight_layout()
    return fig


def plot_monthly_returns_heatmap(daily_returns: pd.Series, title: str = "Monthly Returns") -> plt.Figure:
    monthly = (1 + daily_returns).resample("ME").prod() - 1
    df = monthly.to_frame("ret")
    df["year"] = df.index.year
    df["month"] = df.index.month
    pivot = df.pivot(index="year", columns="month", values="ret")
    pivot = pivot.reindex(columns=range(1, 13))

    fig, ax = plt.subplots(figsize=(12, max(3, 0.4 * len(pivot))))
    im = ax.imshow(pivot.values * 100, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(pivot)))
    ax.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v * 100:.1f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, label="%")
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_yearly_returns(daily_returns: pd.Series, title: str = "Yearly Returns") -> plt.Figure:
    yearly = (1 + daily_returns).resample("YE").prod() - 1
    fig, ax = plt.subplots(figsize=_FIGSIZE)
    colors = ["seagreen" if v >= 0 else "firebrick" for v in yearly.values]
    ax.bar([str(y.year) for y in yearly.index], yearly.values * 100, color=colors)
    ax.set_ylabel("Return (%)")
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_parameter_heatmap(param_grid_results: pd.DataFrame, x_col: str, y_col: str, value_col: str,
                            title: str = "Parameter Heatmap") -> plt.Figure:
    pivot = param_grid_results.pivot(index=y_col, columns=x_col, values=value_col)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pivot.values, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    fig.colorbar(im, ax=ax, label=value_col)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_strategy_comparison(summary_df: pd.DataFrame, metric: str = "sharpe", title: str = "Strategy Comparison") -> plt.Figure:
    ordered = summary_df.sort_values(metric, ascending=False)
    fig, ax = plt.subplots(figsize=(10, max(3, 0.35 * len(ordered))))
    ax.barh(ordered["strategy_id"].astype(str), ordered[metric])
    ax.invert_yaxis()
    ax.set_xlabel(metric)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_correlation_matrix(returns_wide: pd.DataFrame, title: str = "Correlation Matrix") -> plt.Figure:
    corr = returns_wide.corr()
    fig, ax = plt.subplots(figsize=(max(6, 0.5 * len(corr)), max(5, 0.5 * len(corr))))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index, fontsize=7)
    fig.colorbar(im, ax=ax, label="correlation")
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_portfolio_allocation(weights: dict[str, float], title: str = "Portfolio Allocation") -> plt.Figure:
    labels = list(weights.keys())
    values = list(weights.values())
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_candidate_ranking(candidates_df: pd.DataFrame, score_col: str = "composite_score",
                            label_col: str = "symbol", top_n: int = 20,
                            title: str = "Candidate Ranking") -> plt.Figure:
    top = candidates_df.nlargest(top_n, score_col).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, max(3, 0.3 * len(top))))
    ax.barh(top[label_col].astype(str), top[score_col])
    ax.set_xlabel(score_col)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def save_figure(fig: plt.Figure, path: str) -> None:
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
