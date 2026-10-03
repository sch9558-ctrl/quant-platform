"""US-equity tax-loss harvesting recommendation engine (research support)."""
from __future__ import annotations
from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class HarvestRecommendation:
    symbol:str
    unrealized_loss_krw:float
    suggested_loss_to_realize_krw:float
    reason:str
    def to_dict(self):return asdict(self)

def recommend_tax_loss_harvest(realized_net_gain_krw,positions,*,deduction_krw=2_500_000,month=12):
    excess=max(0.,float(realized_net_gain_krw)-float(deduction_krw))
    if month not in (11,12) or excess<=0:return []
    losses=[]
    for p in positions:
        basis=float(p.get("cost_basis_krw",0));value=float(p.get("market_value_krw",0));loss=max(0.,basis-value)
        if loss>0:losses.append((str(p["symbol"]),loss))
    losses.sort(key=lambda x:x[1],reverse=True);out=[];remaining=excess
    for symbol,loss in losses:
        if remaining<=0:break
        use=min(loss,remaining);out.append(HarvestRecommendation(symbol,loss,use,f"연간 실현이익 공제 초과분 {excess:,.0f}원 상쇄 후보"));remaining-=use
    return out
