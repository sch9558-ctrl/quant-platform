"""Deterministic multi-agent investment committee with an absolute risk veto."""
from __future__ import annotations
from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class AgentVote:
    name:str
    score:float
    approve:bool
    veto:bool=False
    reasons:tuple[str,...]=()

@dataclass(frozen=True)
class CommitteeDecision:
    final_signal:str
    weighted_score:float
    vetoed:bool
    votes:tuple[AgentVote,...]
    def to_dict(self):return asdict(self)

class ScoringAgent:
    name="agent"
    def __init__(self,weights):self.weights=dict(weights)
    def evaluate(self,features):
        used=[];total=0.;denom=0.
        for k,w in self.weights.items():
            if k in features and features[k] is not None:
                v=max(0.,min(100.,float(features[k])));total+=v*float(w);denom+=abs(float(w));used.append(k)
        score=total/denom if denom else 0.
        return AgentVote(self.name,score,score>=60,False,tuple(used))

class FundamentalAgent(ScoringAgent):
    name="fundamental"
    def __init__(self):super().__init__({"valuation":.30,"roe":.25,"balance_sheet":.20,"consensus":.25})
class TechnicalAgent(ScoringAgent):
    name="technical"
    def __init__(self):super().__init__({"trend":.35,"flow":.30,"bollinger":.15,"momentum":.20})
class SentimentAgent(ScoringAgent):
    name="sentiment"
    def __init__(self):super().__init__({"report_conviction":.55,"news_sentiment":.45})

class RiskManagerAgent:
    name="risk_manager"
    def evaluate(self,features):
        failures=[]
        if not features.get("filing_risk_cleared",True):failures.append("filing_risk")
        if float(features.get("max_correlation",0) or 0)>=.80:failures.append("correlation")
        if float(features.get("vix",0) or 0)>30:failures.append("vix")
        if features.get("watchdog_safe_mode",False):failures.append("watchdog")
        veto=bool(failures)
        return AgentVote(self.name,0 if veto else 100,not veto,veto,tuple(failures))

class AgentCommittee:
    def __init__(self,approval_threshold=80.0,weights=None):
        self.approval_threshold=float(approval_threshold);self.weights=weights or {"fundamental":.40,"technical":.35,"sentiment":.25}
        self.agents=(FundamentalAgent(),TechnicalAgent(),SentimentAgent());self.risk=RiskManagerAgent()
    def decide(self,features):
        votes=[a.evaluate(features) for a in self.agents];risk=self.risk.evaluate(features);votes.append(risk)
        weighted=sum(v.score*self.weights.get(v.name,0) for v in votes);approved=(not risk.veto) and weighted>=self.approval_threshold
        return CommitteeDecision("FINAL_APPROVED_BUY" if approved else "REJECT",float(weighted),risk.veto,tuple(votes))
