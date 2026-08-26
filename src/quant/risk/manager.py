"""Risk Manager (spec section 17). Every Paper/Live order (and, in
research mode, every proposed portfolio rebalance) is expected to pass
through `RiskManager.check_order` before being acted on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant import config


@dataclass
class PortfolioState:
    nav: float
    peak_nav: float
    positions: dict[str, float]              # symbol -> current weight [0,1]
    daily_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    returns_history: dict[str, pd.Series] = field(default_factory=dict)  # for correlation checks

    @property
    def current_drawdown(self) -> float:
        if self.peak_nav <= 0:
            return 0.0
        return self.nav / self.peak_nav - 1


@dataclass
class RiskCheckResult:
    symbol: str
    requested_weight: float
    approved_weight: float
    approved: bool
    reasons: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, risk_cfg: dict | None = None):
        self.cfg = risk_cfg or config.risk_config()

    def check_order(
        self,
        symbol: str,
        target_weight: float,
        state: PortfolioState,
        sector: str | None = None,
    ) -> RiskCheckResult:
        reasons: list[str] = []
        adjusted = max(0.0, target_weight)

        pos_limits = self.cfg["position_limits"]
        loss_limits = self.cfg["loss_limits"]

        # -- hard stops: no new risk-increasing entries at all -------------
        if state.daily_pnl_pct <= -loss_limits["max_daily_loss_pct"]:
            reasons.append(f"daily loss limit breached ({state.daily_pnl_pct:.1%}) -- no new entries today")
            adjusted = min(adjusted, state.positions.get(symbol, 0.0))

        if state.current_drawdown <= -loss_limits["max_drawdown_pct"]:
            reasons.append(f"max drawdown breached ({state.current_drawdown:.1%}) -- de-risking, no new entries")
            adjusted = min(adjusted, state.positions.get(symbol, 0.0))

        if state.consecutive_losses >= loss_limits["consecutive_loss_limit"]:
            reasons.append(f"consecutive loss limit reached ({state.consecutive_losses}) -- pause new entries")
            adjusted = min(adjusted, state.positions.get(symbol, 0.0))

        # -- position size cap ---------------------------------------------
        if adjusted > pos_limits["max_position_weight"]:
            adjusted = pos_limits["max_position_weight"]
            reasons.append("position size capped at max_position_weight")

        # -- gross exposure cap ----------------------------------------------
        other_exposure = sum(w for s, w in state.positions.items() if s != symbol)
        if other_exposure + adjusted > pos_limits["max_gross_exposure"]:
            allowed = max(0.0, pos_limits["max_gross_exposure"] - other_exposure)
            if allowed < adjusted:
                adjusted = allowed
                reasons.append("gross exposure cap reached -- position size reduced")

        # -- correlation limit -----------------------------------------------
        if adjusted > state.positions.get(symbol, 0.0):
            correlated_with = self._breaches_correlation_limit(symbol, state)
            if correlated_with:
                adjusted = state.positions.get(symbol, 0.0)
                reasons.append(f"highly correlated with existing position '{correlated_with}' -- new exposure blocked")

        return RiskCheckResult(
            symbol=symbol, requested_weight=target_weight, approved_weight=adjusted,
            approved=adjusted > 0, reasons=reasons,
        )

    def _breaches_correlation_limit(self, symbol: str, state: PortfolioState) -> str | None:
        corr_cfg = self.cfg["correlation"]
        target_ret = state.returns_history.get(symbol)
        if target_ret is None:
            return None
        held_symbols = [s for s, w in state.positions.items() if w > 1e-9 and s != symbol]
        for held in held_symbols:
            held_ret = state.returns_history.get(held)
            if held_ret is None:
                continue
            aligned = pd.concat([target_ret, held_ret], axis=1, join="inner").tail(corr_cfg["correlation_lookback_days"])
            if len(aligned) < 10:
                continue
            corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
            if corr is not None and corr >= corr_cfg["max_pairwise_correlation"]:
                return held
        return None

    def position_size(self, signal_strength: float, volatility: float | None) -> float:
        """Volatility-target position sizing (spec: "Position Sizing")."""
        cfg = self.cfg["position_sizing"]
        if cfg["method"] == "volatility_target" and volatility:
            size = cfg["target_annual_vol"] / volatility
        elif cfg["method"] == "signal_weight":
            size = signal_strength
        else:
            size = 1.0
        return float(min(max(size, 0.0), cfg["max_leverage"]))

    def check_stop_loss(self, entry_price: float, current_price: float, highest_price_since_entry: float | None = None) -> tuple[bool, str | None]:
        """Return (should_exit, reason) for stop-loss / trailing-stop rules."""
        cfg = self.cfg["stops"]
        if cfg["use_stop_loss"] and entry_price > 0:
            if current_price / entry_price - 1 <= -cfg["stop_loss_pct"]:
                return True, "stop_loss"
        if cfg["use_trailing_stop"] and highest_price_since_entry and highest_price_since_entry > 0:
            if current_price / highest_price_since_entry - 1 <= -cfg["trailing_stop_pct"]:
                return True, "trailing_stop"
        return False, None
