"""Portfolio-level risk limits and kill-switch logic."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass(frozen=True)
class RiskGuardStatus:
    var95_parametric: float
    var95_historical: float
    max_drawdown: float
    action: str
    allow_new_entries: bool
    liquidate_all: bool


class RiskGuard:
    def __init__(
        self,
        soft_drawdown: float = -0.05,
        hard_drawdown: float = -0.08,
        confidence: float = 0.95,
        min_entry_risk_reward: float = 2.5,
        min_risk_reward: float | None = None,
    ):
        if not 0.5 < confidence < 1:
            raise ValueError("confidence must be between 0.5 and 1")
        self.soft_drawdown = float(soft_drawdown)
        self.hard_drawdown = float(hard_drawdown)
        self.confidence = float(confidence)
        self.min_entry_risk_reward = float(min_entry_risk_reward if min_risk_reward is None else min_risk_reward)

    @staticmethod
    def portfolio_returns(returns: pd.DataFrame, weights) -> pd.Series:
        if returns is None or returns.empty:
            return pd.Series(dtype=float)
        w = pd.Series(weights, dtype=float).reindex(returns.columns).fillna(0.0)
        return returns.astype(float).fillna(0.0).dot(w)

    def value_at_risk(self, returns, weights=None) -> tuple[float, float]:
        if isinstance(returns, pd.DataFrame):
            r = self.portfolio_returns(returns, weights)
        else:
            r = pd.Series(returns, dtype=float).dropna()
        r = r.replace([np.inf, -np.inf], np.nan).dropna()
        if r.empty:
            return 0.0, 0.0
        z = abs(float(norm.ppf(1.0 - self.confidence)))
        mu = float(r.mean())
        sd = float(r.std(ddof=1)) if len(r) > 1 else 0.0
        parametric = max(0.0, -(mu - z * sd))
        historical = max(0.0, -float(r.quantile(1.0 - self.confidence)))
        return float(parametric), float(historical)

    @staticmethod
    def max_drawdown(nav) -> float:
        s = pd.Series(nav, dtype=float).dropna()
        if s.empty:
            return 0.0
        peaks = s.cummax()
        dd = s / peaks - 1.0
        return float(dd.min())

    def drawdown_action(self, nav) -> tuple[str, bool, bool]:
        dd = self.max_drawdown(nav)
        eps = 1e-12
        if dd <= self.hard_drawdown + eps:
            return "HARD_KILL_SWITCH", False, True
        if dd <= self.soft_drawdown + eps:
            return "SOFT_STOP", False, False
        return "NORMAL", True, False

    def evaluate(self, returns, nav, weights=None) -> RiskGuardStatus:
        pvar, hvar = self.value_at_risk(returns, weights)
        dd = self.max_drawdown(nav)
        action, allow, liquidate = self.drawdown_action(nav)
        return RiskGuardStatus(pvar, hvar, dd, action, allow, liquidate)

    @staticmethod
    def atr_trailing_stop(highest_high: float, atr20: float, multiple: float = 2.5) -> float:
        if highest_high <= 0 or atr20 < 0 or multiple <= 0:
            raise ValueError("invalid trailing-stop inputs")
        return float(max(0.0, highest_high - multiple * atr20))

    def entry_risk_reward_allowed(self, expected_reward: float, expected_risk: float) -> bool:
        """Entry-time filter only; never use shrinking remaining R/R to force an exit."""
        if expected_risk <= 0:
            return expected_reward > 0
        return (float(expected_reward) / float(expected_risk)) >= self.min_entry_risk_reward

    @staticmethod
    def position_exit_reason(
        *,
        current_price: float,
        trailing_stop: float,
        entry_price: float | None = None,
        sessions_held: int | None = None,
        time_stop_sessions: int = 15,
        time_stop_low: float = -0.015,
        time_stop_high: float = 0.020,
        expected_reward: float | None = None,
        expected_risk: float | None = None,
    ) -> str | None:
        """Single authoritative position-exit decision.

        Remaining reward/risk naturally falls as a winning trade approaches
        its target, so it must not be reused as a liquidation trigger.
        Time-stop logic is centralized here as well so ExitEngine cannot
        become a second, conflicting exit authority.
        """
        if current_price <= trailing_stop:
            return "TRAILING_STOP"
        if (
            entry_price is not None
            and entry_price > 0
            and sessions_held is not None
            and int(sessions_held) >= int(time_stop_sessions)
        ):
            ret = float(current_price / entry_price - 1.0)
            if float(time_stop_low) <= ret <= float(time_stop_high):
                return "TIME_EXPIRED_EXIT"
        return None
