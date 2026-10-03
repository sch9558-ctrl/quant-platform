"""Dynamic exits: Chandelier trailing stop and time stop."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class ExitDecision:
    action: str
    trailing_stop: float
    sessions_held: int
    return_pct: float
    def to_dict(self): return asdict(self)

class ExitEngine:
    def __init__(self, atr_multiple=2.5, time_stop_sessions=15, time_stop_low=-.015, time_stop_high=.020):
        self.atr_multiple=float(atr_multiple); self.time_stop_sessions=int(time_stop_sessions)
        self.time_stop_low=float(time_stop_low); self.time_stop_high=float(time_stop_high)

    def update_trailing_stop(self, highest_high_since_entry, atr14, previous_stop=None):
        if highest_high_since_entry<=0 or atr14<0: raise ValueError("invalid Chandelier inputs")
        candidate=max(0.0,float(highest_high_since_entry)-self.atr_multiple*float(atr14))
        return float(max(candidate,previous_stop or 0.0))

    def evaluate(self, *, current_price, entry_price, highest_high_since_entry, atr14, sessions_held, previous_stop=None):
        if current_price<=0 or entry_price<=0: raise ValueError("prices must be positive")
        stop=self.update_trailing_stop(highest_high_since_entry,atr14,previous_stop); ret=float(current_price/entry_price-1)
        if current_price<=stop: action="TAKE_PROFIT" if ret>0 else "STOP_LOSS"
        elif sessions_held>=self.time_stop_sessions and self.time_stop_low<=ret<=self.time_stop_high: action="TIME_EXPIRED_EXIT"
        else: action="HOLD"
        return ExitDecision(action,stop,int(sessions_held),ret)
