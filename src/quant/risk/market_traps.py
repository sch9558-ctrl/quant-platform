"""Market-specific event and leverage traps for KRX/US entries."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import pandas as pd

@dataclass(frozen=True)
class MarketTrapAssessment:
    risk_cleared: bool
    reasons: tuple[str,...]
    def to_dict(self): return asdict(self)

class MarketTrapDetector:
    def __init__(self, earnings_blackout_days=3, max_credit_balance_pct=5.0, max_gap_down_pct=-3.5):
        self.earnings_blackout_days=int(earnings_blackout_days); self.max_credit_balance_pct=float(max_credit_balance_pct); self.max_gap_down_pct=float(max_gap_down_pct)

    def assess(self, *, as_of, earnings_date=None, credit_balance_pct=None, open_price=None, previous_close=None):
        reasons=[]; now=pd.Timestamp(as_of).normalize()
        if earnings_date is not None:
            event=pd.Timestamp(earnings_date).normalize(); delta=int((event-now).days)
            if 0<=delta<=self.earnings_blackout_days: reasons.append(f"EARNINGS_BLACKOUT_D-{delta}")
        if credit_balance_pct is not None and float(credit_balance_pct)>=self.max_credit_balance_pct: reasons.append("HIGH_KRX_CREDIT_BALANCE")
        if open_price is not None and previous_close not in (None,0):
            gap=(float(open_price)/float(previous_close)-1)*100
            if gap<=self.max_gap_down_pct: reasons.append("GAP_DOWN_HOLD")
        return MarketTrapAssessment(not reasons,tuple(reasons))
