"""Four-agent virtual investment committee with absolute risk veto."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentVote:
    name:str
    score:float
    approve:bool
    reason:str=""
    veto:bool=False

class FundamentalAgent:
    def evaluate(self,score:float,reason:str="")->AgentVote:return AgentVote("Fundamental",float(score),score>=60,reason)
class TechnicalAgent:
    def evaluate(self,score:float,reason:str="")->AgentVote:return AgentVote("Technical",float(score),score>=60,reason)
class SentimentAgent:
    def evaluate(self,score:float,reason:str="")->AgentVote:return AgentVote("Sentiment",float(score),score>=60,reason)
class RiskManagerAgent:
    def evaluate(self,risk_cleared:bool,score:float=100,reason:str="")->AgentVote:return AgentVote("RiskManager",float(score),risk_cleared,reason,veto=not risk_cleared)

class AgentCommittee:
    def decide(self,fundamental:AgentVote,technical:AgentVote,sentiment:AgentVote,risk:AgentVote,threshold:float=80.0):
        if risk.veto:return {"decision":"VETOED","approved":False,"score":0.0,"votes":[fundamental,technical,sentiment,risk]}
        weighted=0.4*fundamental.score+0.35*technical.score+0.25*sentiment.score
        approved=bool(weighted>=threshold and fundamental.approve and technical.approve and sentiment.approve)
        return {"decision":"FINAL_APPROVED_BUY" if approved else "WAIT","approved":approved,"score":float(weighted),"votes":[fundamental,technical,sentiment,risk]}
