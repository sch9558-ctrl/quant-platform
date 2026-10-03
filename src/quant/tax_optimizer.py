"""US equity tax-loss harvesting recommendation helper."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class HarvestRecommendation:
    symbol:str
    unrealized_loss_krw:float
    suggested_realization_krw:float

def tax_loss_harvest(realized_gain_krw:float,positions:list[dict],exemption_krw:float=2_500_000):
    excess=max(0.0,float(realized_gain_krw)-float(exemption_krw))
    if excess<=0:return []
    losses=sorted([(str(p["symbol"]),max(0.0,-float(p.get("unrealized_pnl_krw",0)))) for p in positions],key=lambda x:x[1],reverse=True)
    out=[]; remaining=excess
    for symbol,loss in losses:
        if remaining<=0:break
        use=min(loss,remaining)
        if use>0:out.append(HarvestRecommendation(symbol,loss,use)); remaining-=use
    return out
