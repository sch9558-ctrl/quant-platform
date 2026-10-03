"""Cross-asset risk gates for Korea and US entries."""
from __future__ import annotations
from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class MacroGate:
    macro_risk_elevated:bool
    position_scale:float
    block_high_beta_growth:bool
    reasons:tuple[str,...]
    def to_dict(self):return asdict(self)

def evaluate_macro_gate(*,market,usdkrw_1d_pct=None,sox_1d_pct=None,vix=None,us10y_change_bp=None):
    reasons=[];scale=1.;block=False
    if market=="korea":
        if usdkrw_1d_pct is not None and float(usdkrw_1d_pct)>=.8:reasons.append("USDKRW_SPIKE")
        if sox_1d_pct is not None and float(sox_1d_pct)<=-2.5:reasons.append("SOX_CRASH")
        if reasons:scale=.5
    elif market=="us":
        if vix is not None and float(vix)>25:reasons.append("VIX_ABOVE_25");block=True
        if us10y_change_bp is not None and float(us10y_change_bp)>=15:reasons.append("US10Y_RATE_SHOCK");scale=min(scale,.75)
    else:raise ValueError("market must be korea or us")
    return MacroGate(bool(reasons),scale,block,tuple(reasons))
