"""Chandelier trailing stop and time-stop exit engine."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ExitDecision:
    signal: str
    trailing_stop: float
    days_held: int
    cumulative_return: float

class ExitEngine:
    def __init__(self,atr_multiple:float=2.5,time_stop_days:int=15):
        self.atr_multiple=float(atr_multiple); self.time_stop_days=int(time_stop_days)

    def update(self,highest_high_since_entry:float,atr14:float,current_price:float,entry_price:float,
               days_held:int,previous_trailing_stop:float|None=None)->ExitDecision:
        raw=float(highest_high_since_entry)-self.atr_multiple*float(atr14)
        trailing=max(raw,float(previous_trailing_stop)) if previous_trailing_stop is not None else raw
        ret=float(current_price)/float(entry_price)-1
        if current_price<=trailing:
            signal="TAKE_PROFIT"
        elif days_held>=self.time_stop_days and -0.015<=ret<=0.02:
            signal="TIME_EXPIRED_EXIT"
        else:
            signal="HOLD"
        return ExitDecision(signal,float(trailing),int(days_held),ret)
