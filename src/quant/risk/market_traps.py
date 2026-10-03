"""Market-specific pre-entry traps for Korea and US equities."""
from __future__ import annotations
import pandas as pd

def earnings_blackout(as_of,earnings_date,days_before:int=3)->bool:
    if not earnings_date:return False
    a=pd.Timestamp(as_of).normalize(); e=pd.Timestamp(earnings_date).normalize()
    return pd.Timedelta(0)<=e-a<=pd.Timedelta(days=int(days_before))

def credit_balance_risk(credit_ratio_pct:float|None,threshold_pct:float=5.0)->bool:
    return credit_ratio_pct is not None and float(credit_ratio_pct)>=threshold_pct

def gap_down_risk(open_price:float,previous_close:float,threshold:float=-0.035)->bool:
    if previous_close<=0:return True
    return open_price/previous_close-1<=threshold

def risk_cleared(as_of,earnings_date=None,credit_ratio_pct=None,open_price=None,previous_close=None)->bool:
    if earnings_blackout(as_of,earnings_date):return False
    if credit_balance_risk(credit_ratio_pct):return False
    if open_price is not None and previous_close is not None and gap_down_risk(open_price,previous_close):return False
    return True
