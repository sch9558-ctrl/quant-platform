"""Institutional Black-Litterman portfolio optimizer.

This module treats analyst/factor views as uncertain observations layered on
top of a market-cap equilibrium prior. Cash is an explicit residual allocation:
weights are long-only, capped per name, and total risky exposure may be < 100%.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize


@dataclass(frozen=True)
class BlackLittermanPosterior:
    prior_returns: pd.Series
    expected_returns: pd.Series
    covariance: pd.DataFrame
    omega: np.ndarray


@dataclass(frozen=True)
class PortfolioOptimizationResult:
    weights: pd.Series
    cash_weight: float
    expected_return: float
    volatility: float
    utility: float
    success: bool
    message: str


class BlackLittermanOptimizer:
    def __init__(
        self,
        risk_aversion: float = 2.5,
        tau: float = 0.05,
        max_weight: float = 0.10,
        sector_band: float = 0.05,
    ):
        if risk_aversion <= 0 or tau <= 0:
            raise ValueError("risk_aversion and tau must be positive")
        if not 0 < max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")
        self.risk_aversion = float(risk_aversion)
        self.tau = float(tau)
        self.max_weight = float(max_weight)
        self.sector_band = float(sector_band)

    @staticmethod
    def _cov_frame(covariance, symbols: Sequence[str] | None = None) -> pd.DataFrame:
        if isinstance(covariance, pd.DataFrame):
            cov = covariance.astype(float).copy()
            if cov.shape[0] != cov.shape[1]:
                raise ValueError("covariance must be square")
            return cov
        arr = np.asarray(covariance, dtype=float)
        if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
            raise ValueError("covariance must be square")
        labels = list(symbols or [str(i) for i in range(arr.shape[0])])
        if len(labels) != arr.shape[0]:
            raise ValueError("symbols length must match covariance")
        return pd.DataFrame(arr, index=labels, columns=labels)

    def implied_equilibrium_returns(
        self,
        covariance,
        market_weights: Mapping[str, float] | pd.Series | Sequence[float],
    ) -> pd.Series:
        cov = self._cov_frame(covariance)
        if isinstance(market_weights, Mapping):
            w = pd.Series(market_weights, dtype=float).reindex(cov.index).fillna(0.0)
        elif isinstance(market_weights, pd.Series):
            w = market_weights.astype(float).reindex(cov.index).fillna(0.0)
        else:
            w = pd.Series(np.asarray(market_weights, dtype=float), index=cov.index)
        if (w < 0).any() or w.sum() <= 0:
            raise ValueError("market_weights must be non-negative with positive sum")
        w = w / w.sum()
        pi = self.risk_aversion * cov.to_numpy() @ w.to_numpy()
        return pd.Series(pi, index=cov.index, name="implied_equilibrium_return")

    def confidence_omega(
        self,
        covariance,
        P,
        confidences: Sequence[float],
    ) -> np.ndarray:
        cov = self._cov_frame(covariance)
        p = np.atleast_2d(np.asarray(P, dtype=float))
        if p.shape[1] != len(cov):
            raise ValueError("P must have one column per asset")
        c = np.asarray(confidences, dtype=float)
        if len(c) != p.shape[0]:
            raise ValueError("confidences must match number of views")
        c = np.clip(c, 0.05, 0.99)
        base = np.diag(p @ (self.tau * cov.to_numpy()) @ p.T)
        omega_diag = np.maximum(base * (1.0 - c) / c, 1e-12)
        return np.diag(omega_diag)

    def posterior(
        self,
        covariance,
        market_weights,
        P,
        Q,
        *,
        omega: np.ndarray | None = None,
        confidences: Sequence[float] | None = None,
    ) -> BlackLittermanPosterior:
        cov = self._cov_frame(covariance)
        pi = self.implied_equilibrium_returns(cov, market_weights)
        p = np.atleast_2d(np.asarray(P, dtype=float))
        q = np.asarray(Q, dtype=float).reshape(-1)
        if p.shape != (len(q), len(cov)):
            raise ValueError("P/Q dimensions do not match covariance")
        if omega is None:
            if confidences is None:
                omega = np.diag(np.maximum(np.diag(p @ (self.tau * cov.to_numpy()) @ p.T), 1e-12))
            else:
                omega = self.confidence_omega(cov, p, confidences)
        omega = np.asarray(omega, dtype=float)
        if omega.shape != (len(q), len(q)):
            raise ValueError("omega has wrong shape")

        tau_cov = self.tau * cov.to_numpy()
        inv_tau = np.linalg.pinv(tau_cov)
        inv_omega = np.linalg.pinv(omega)
        middle = np.linalg.pinv(inv_tau + p.T @ inv_omega @ p)
        mu = middle @ (inv_tau @ pi.to_numpy() + p.T @ inv_omega @ q)
        post_cov = cov.to_numpy() + middle
        return BlackLittermanPosterior(
            prior_returns=pi,
            expected_returns=pd.Series(mu, index=cov.index, name="posterior_expected_return"),
            covariance=pd.DataFrame(post_cov, index=cov.index, columns=cov.columns),
            omega=omega,
        )

    def optimize(
        self,
        expected_returns: Mapping[str, float] | pd.Series | Sequence[float],
        covariance,
        *,
        symbols: Sequence[str] | None = None,
        sectors: Mapping[str, str] | None = None,
        benchmark_sector_weights: Mapping[str, float] | None = None,
        initial_weights: Mapping[str, float] | pd.Series | None = None,
    ) -> PortfolioOptimizationResult:
        cov = self._cov_frame(covariance, symbols=symbols)
        if isinstance(expected_returns, Mapping):
            mu = pd.Series(expected_returns, dtype=float).reindex(cov.index)
        elif isinstance(expected_returns, pd.Series):
            mu = expected_returns.astype(float).reindex(cov.index)
        else:
            mu = pd.Series(np.asarray(expected_returns, dtype=float), index=cov.index)
        if mu.isna().any() or len(mu) != len(cov):
            raise ValueError("expected_returns do not align with covariance")
        n = len(cov)
        if initial_weights is None:
            x0 = np.full(n, min(self.max_weight, 1.0 / max(n, 1)))
        else:
            x0 = pd.Series(initial_weights, dtype=float).reindex(cov.index).fillna(0.0).to_numpy()
            x0 = np.clip(x0, 0.0, self.max_weight)
        if x0.sum() > 1:
            x0 /= x0.sum()

        sigma = cov.to_numpy()
        muv = mu.to_numpy()

        def objective(w):
            return -(float(w @ muv) - 0.5 * self.risk_aversion * float(w @ sigma @ w))

        constraints = [{"type": "ineq", "fun": lambda w: 1.0 - float(np.sum(w))}]
        if sectors and benchmark_sector_weights:
            sector_names = sorted(set(sectors.get(s) for s in cov.index if sectors.get(s) is not None))
            for sector in sector_names:
                idx = np.array([i for i, s in enumerate(cov.index) if sectors.get(s) == sector], dtype=int)
                if not len(idx) or sector not in benchmark_sector_weights:
                    continue
                bench = float(benchmark_sector_weights[sector])
                lower = max(0.0, bench - self.sector_band)
                upper = min(1.0, bench + self.sector_band)
                constraints.append({"type": "ineq", "fun": lambda w, idx=idx, lower=lower: float(np.sum(w[idx])) - lower})
                constraints.append({"type": "ineq", "fun": lambda w, idx=idx, upper=upper: upper - float(np.sum(w[idx]))})

        res = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=[(0.0, self.max_weight)] * n,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12},
        )
        w = np.clip(np.asarray(res.x, dtype=float), 0.0, self.max_weight)
        if w.sum() > 1 + 1e-8:
            w /= w.sum()
        exp_ret = float(w @ muv)
        vol = float(np.sqrt(max(w @ sigma @ w, 0.0)))
        utility = exp_ret - 0.5 * self.risk_aversion * vol * vol
        return PortfolioOptimizationResult(
            weights=pd.Series(w, index=cov.index, name="weight"),
            cash_weight=float(max(0.0, 1.0 - w.sum())),
            expected_return=exp_ret,
            volatility=vol,
            utility=float(utility),
            success=bool(res.success),
            message=str(res.message),
        )
