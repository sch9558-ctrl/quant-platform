from quant.decision.agent_committee import FundamentalAgent,TechnicalAgent,SentimentAgent,RiskManagerAgent,AgentCommittee

def test_committee_approves_only_without_risk_veto():
    c=AgentCommittee()
    f=FundamentalAgent().evaluate(92); t=TechnicalAgent().evaluate(85); s=SentimentAgent().evaluate(88)
    ok=c.decide(f,t,s,RiskManagerAgent().evaluate(True))
    blocked=c.decide(f,t,s,RiskManagerAgent().evaluate(False,reason="filing risk"))
    assert ok["approved"] and ok["decision"]=="FINAL_APPROVED_BUY"
    assert not blocked["approved"] and blocked["decision"]=="VETOED"
