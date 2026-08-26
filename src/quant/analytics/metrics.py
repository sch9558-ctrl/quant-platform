"""Performance metrics (spec section 12).

Every function here takes plain pandas Series (an equity curve or a daily
return series) rather than a `BacktestResult`, so they're independently
testable and reusable outside the backtester (e.g. on a live paper-trading
NAV series). `compute_metrics` is the one-stop entry point that assembles
everything, including trade-level statistics reconstructed from the
backtester's per-day weight history.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class RoundTripTrade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    holding_days: int
    return_pct: float


@dataclass
class PerformanceMetrics:
    total_return: float
    cagr: float
    annual_vol: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    profit_factor: float | None
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    avg_turnover: float
    num_trades: int
    avg_holding_period_days: float | None
    exposure: float
    max_drawdown_recovery_days: int | None
    alpha_annualized: float | None = None
    beta: float | None = None
    information_ratio: float | None = None
    downside_capture: float | None = None
    upside_capture: float | None = None
    extra: dict = field(default_factory=dict)


def cumulative_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    if n_years <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (1 / n_years) - 1)


def annualized_volatility(daily_returns: pd.Series) -> float:
    return float(daily_returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(daily_returns) > 1 else 0.0


def sharpe_ratio(daily_returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    if len(daily_returns) < 2 or daily_returns.std(ddof=1) == 0:
        return 0.0
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = daily_returns - rf_daily
    return float(excess.mean() / excess.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(daily_returns: pd.Series, risk_free_annual: float = 0.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = daily_returns - rf_daily
    downside = excess[excess < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
    if not downside_std:
        return 0.0
    return float(excess.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))


def drawdown_series(equity: pd.Series) -> pd.Series:
    running_max = equity.cummax()
    return equity / running_max - 1


def max_drawdown(equity: pd.Series) -> float:
    dd = drawdown_series(equity)
    return float(dd.min()) if len(dd) else 0.0


def max_drawdown_recovery_days(equity: pd.Series) -> int | None:
    """Trading days from the trough of the worst drawdown back to a new
    equity high. None if the backtest ends before recovering."""
    dd = drawdown_series(equity)
    if dd.empty:
        return None
    trough_date = dd.idxmin()
    trough_value = equity.loc[trough_date]
    prior_peak = equity.loc[:trough_date].max()
    after = equity.loc[trough_date:]
    recovered = after[after >= prior_peak]
    if recovered.empty:
        return None
    recovery_date = recovered.index[0]
    return int((recovery_date - trough_date).days)


def calmar_ratio(cagr_value: float, max_dd: float) -> float:
    if max_dd == 0:
        return 0.0
    return float(cagr_value / abs(max_dd))


def alpha_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series, annualize: bool = True) -> tuple[float, float]:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 10 or aligned.iloc[:, 1].var() == 0:
        return (0.0, 0.0)
    y, x = aligned.iloc[:, 0].to_numpy(), aligned.iloc[:, 1].to_numpy()
    beta, alpha = np.polyfit(x, y, 1)
    alpha_ann = alpha * TRADING_DAYS_PER_YEAR if annualize else alpha
    return float(alpha_ann), float(beta)


def information_ratio(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 10:
        return 0.0
    active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    if active.std(ddof=1) == 0:
        return 0.0
    return float(active.mean() / active.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def capture_ratios(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> tuple[float | None, float | None]:
    aligned = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if aligned.empty:
        return (None, None)
    up = aligned[aligned.iloc[:, 1] > 0]
    down = aligned[aligned.iloc[:, 1] < 0]
    up_capture = float(up.iloc[:, 0].mean() / up.iloc[:, 1].mean()) if len(up) and up.iloc[:, 1].mean() != 0 else None
    down_capture = float(down.iloc[:, 0].mean() / down.iloc[:, 1].mean()) if len(down) and down.iloc[:, 1].mean() != 0 else None
    return (up_capture, down_capture)


def reconstruct_round_trip_trades(weights: pd.DataFrame, ohlcv_map: dict[str, pd.DataFrame]) -> list[RoundTripTrade]:
    """Detect contiguous nonzero-weight streaks per symbol in the
    backtester's daily weight history and treat each streak as one
    round-trip trade, valued by that symbol's adj_close return over the
    streak. This is a simplification (it ignores mid-streak weight
    changes for cross-sectional strategies) used only for diagnostic
    trade statistics (win rate, profit factor, ...) -- the authoritative
    P&L is always the equity curve itself.
    """
    trades: list[RoundTripTrade] = []
    if weights is None or weights.empty:
        return trades

    for sym in weights.columns:
        w = weights[sym]
        is_on = w > 1e-9
        if not is_on.any():
            continue
        close = ohlcv_map.get(sym, pd.DataFrame()).get("adj_close")
        if close is None:
            continue

        streak_id = (is_on != is_on.shift(1, fill_value=False)).cumsum()
        for _, group in w[is_on].groupby(streak_id[is_on]):
            entry_date, exit_date = group.index[0], group.index[-1]
            try:
                entry_price = close.loc[entry_date]
                exit_price = close.loc[exit_date]
            except KeyError:
                continue
            if pd.isna(entry_price) or pd.isna(exit_price) or entry_price == 0:
                continue
            trades.append(RoundTripTrade(
                symbol=sym, entry_date=entry_date, exit_date=exit_date,
                holding_days=(exit_date - entry_date).days + 1,
                return_pct=float(exit_price / entry_price - 1),
            ))
    return trades


def trade_statistics(trades: list[RoundTripTrade]) -> dict:
    if not trades:
        return {
            "num_trades": 0, "win_rate": None, "avg_win": None, "avg_loss": None,
            "profit_factor": None, "expectancy": None, "avg_holding_period_days": None,
        }
    returns = np.array([t.return_pct for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    gross_profit = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0
    return {
        "num_trades": len(trades),
        "win_rate": float((returns > 0).mean()),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": float(returns.mean()),
        "avg_holding_period_days": float(np.mean([t.holding_days for t in trades])),
    }


def compute_metrics(
    equity: pd.Series,
    daily_returns: pd.Series,
    weights: pd.DataFrame | None = None,
    ohlcv_map: dict[str, pd.DataFrame] | None = None,
    turnover: pd.Series | None = None,
    benchmark_close: pd.Series | None = None,
    risk_free_annual: float = 0.0,
) -> PerformanceMetrics:
    if equity is None or equity.empty:
        return PerformanceMetrics(
            total_return=0.0, cagr=0.0, annual_vol=0.0, sharpe=0.0, sortino=0.0,
            max_drawdown=0.0, calmar=0.0, profit_factor=None, win_rate=None,
            avg_win=None, avg_loss=None, expectancy=None, avg_turnover=0.0,
            num_trades=0, avg_holding_period_days=None, exposure=0.0,
            max_drawdown_recovery_days=None,
        )

    mdd = max_drawdown(equity)
    cg = cagr(equity)

    trades = reconstruct_round_trip_trades(weights, ohlcv_map or {}) if weights is not None else []
    tstats = trade_statistics(trades)

    exposure = float(weights.sum(axis=1).mean()) if weights is not None and not weights.empty else 0.0
    avg_turnover = float(turnover.mean()) if turnover is not None and len(turnover) else 0.0

    metrics = PerformanceMetrics(
        total_return=cumulative_return(equity),
        cagr=cg,
        annual_vol=annualized_volatility(daily_returns),
        sharpe=sharpe_ratio(daily_returns, risk_free_annual),
        sortino=sortino_ratio(daily_returns, risk_free_annual),
        max_drawdown=mdd,
        calmar=calmar_ratio(cg, mdd),
        profit_factor=tstats["profit_factor"],
        win_rate=tstats["win_rate"],
        avg_win=tstats["avg_win"],
        avg_loss=tstats["avg_loss"],
        expectancy=tstats["expectancy"],
        avg_turnover=avg_turnover,
        num_trades=tstats["num_trades"],
        avg_holding_period_days=tstats["avg_holding_period_days"],
        exposure=exposure,
        max_drawdown_recovery_days=max_drawdown_recovery_days(equity),
    )

    if benchmark_close is not None and len(benchmark_close) > 1:
        bench_returns = benchmark_close.pct_change().reindex(daily_returns.index).fillna(0.0)
        alpha, beta = alpha_beta(daily_returns, bench_returns)
        metrics.alpha_annualized = alpha
        metrics.beta = beta
        metrics.information_ratio = information_ratio(daily_returns, bench_returns)
        up_cap, down_cap = capture_ratios(daily_returns, bench_returns)
        metrics.upside_capture = up_cap
        metrics.downside_capture = down_cap

    return metrics
