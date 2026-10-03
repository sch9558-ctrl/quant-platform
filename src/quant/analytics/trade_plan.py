"""Deterministic model trade-plan generation for dashboard candidates."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math

@dataclass(frozen=True)
class TradePlan:
    action: str
    action_ko: str
    entry_low: float
    entry_high: float
    target_1: float
    target_2: float
    target_1_upside_pct: float
    target_2_upside_pct: float
    stop_loss: float
    stop_loss_pct: float
    holding_period_ko: str
    model_confidence: int
    reasons_ko: list[str]
    note_ko: str = "모델 기반 매매 가이드이며 수익을 보장하지 않습니다."
    def to_dict(self): return asdict(self)

def _finite(value, default: float) -> float:
    try:
        value=float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default

def build_trade_plan(candidate) -> dict:
    price=max(_finite(getattr(candidate,"price",0),0),1e-9)
    score=min(max(_finite(getattr(candidate,"composite_score",.5),.5),0),1)
    trend=_finite(getattr(candidate,"trend_score",0),0)
    momentum=_finite(getattr(candidate,"momentum_rank",.5),.5)
    risk=min(max(_finite(getattr(candidate,"risk_score",.5),.5),0),1)
    annual_vol=min(max(_finite(getattr(candidate,"volatility",.25),.25),.05),1.5)
    edge=getattr(candidate,"historical_signal_edge",{}) or {}
    win_rate=_finite(edge.get("win_rate"),.5) if edge.get("n_obs",0)>=5 else .5
    if score>=.74 and trend>=.10 and momentum>=.65 and risk<=.70:
        action,ko="STRONG_BUY","강력 매수(진입)"
    elif score>=.61 and trend>=-.05:
        action,ko="BUY","분할 매수"
    elif score>=.49:
        action,ko="HOLD","홀딩"
    elif score>=.39:
        action,ko="TRIM","분할 매도"
    else:
        action,ko="AVOID","손절/관망"
    stop_pct=min(max(.04+.035*risk+.02*min(annual_vol,.8),.04),.10)
    entry_discount=min(max(stop_pct*.45,.015),.045)
    entry_high=price*1.005 if action=="STRONG_BUY" else price*(1-entry_discount*.20)
    entry_low=price*(1-entry_discount)
    t1pct=min(max(stop_pct*1.5+max(trend,0)*.02,.06),.18)
    t2pct=min(max(stop_pct*2.4+max(momentum-.5,0)*.10,.12),.32)
    holding="스윙~중기 (1~4개월)" if trend>.25 and momentum>.70 else ("스윙 (3주~2개월)" if momentum>.55 else "단기 관찰 (1~4주)")
    confidence=round(100*min(max(.45*score+.20*((trend+1)/2)+.15*momentum+.10*(1-risk)+.10*win_rate,0),1))
    reasons=[f"종합 후보점수 {score:.2f}",f"모멘텀 백분위 {momentum:.2f}",f"추세점수 {trend:+.2f}",f"리스크점수 {risk:.2f}"]
    if edge.get("n_obs",0)>=5: reasons.append(f"유사 과거신호 승률 {win_rate:.0%} (표본 {edge.get('n_obs')})")
    return TradePlan(action,ko,round(entry_low,4),round(entry_high,4),round(price*(1+t1pct),4),round(price*(1+t2pct),4),round(t1pct*100,2),round(t2pct*100,2),round(price*(1-stop_pct),4),round(-stop_pct*100,2),holding,confidence,reasons).to_dict()
