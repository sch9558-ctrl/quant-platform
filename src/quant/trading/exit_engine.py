"""Compatibility adapter for dynamic exits.

RiskGuard is the single authoritative exit/risk policy. This adapter preserves
legacy research callers while delegating trailing-stop and time-stop decisions
to RiskGuard so two independent exit authorities cannot drift apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from quant.risk_guard import RiskGuard


@dataclass(frozen=True)
class ExitDecision:
    action: str
    trailing_stop: float
    sessions_held: int
    return_pct: float

    def to_dict(self):
        return asdict(self)


class ExitEngine:
    def __init__(
        self,
        atr_multiple=2.5,
        time_stop_sessions=15,
        time_stop_low=-0.015,
        time_stop_high=0.020,
    ):
        self.atr_multiple=float(atr_multiple)
        self.time_stop_sessions=int(time_stop_sessions)
        self.time_stop_low=float(time_stop_low)
        self.time_stop_high=float(time_stop_high)

    def update_trailing_stop(self, highest_high_since_entry, atr14, previous_stop=None):
        stop=RiskGuard.atr_trailing_stop(
            float(highest_high_since_entry),
            float(atr14),
            multiple=self.atr_multiple,
        )
        return float(max(stop, previous_stop or 0.0))

    def evaluate(
        self,
        *,
        current_price,
        entry_price,
        highest_high_since_entry,
        atr14,
        sessions_held,
        previous_stop=None,
    ):
        if current_price<=0 or entry_price<=0:
            raise ValueError("prices must be positive")
        stop=self.update_trailing_stop(
            highest_high_since_entry,
            atr14,
            previous_stop=previous_stop,
        )
        ret=float(current_price/entry_price-1.0)
        reason=RiskGuard.position_exit_reason(
            current_price=float(current_price),
            trailing_stop=stop,
            entry_price=float(entry_price),
            sessions_held=int(sessions_held),
            time_stop_sessions=self.time_stop_sessions,
            time_stop_low=self.time_stop_low,
            time_stop_high=self.time_stop_high,
        )
        if reason=="TRAILING_STOP":
            action="TAKE_PROFIT" if ret>0 else "STOP_LOSS"
        elif reason=="TIME_EXPIRED_EXIT":
            action="TIME_EXPIRED_EXIT"
        else:
            action="HOLD"
        return ExitDecision(action,stop,int(sessions_held),ret)
