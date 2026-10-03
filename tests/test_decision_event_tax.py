from quant.decision.agent_committee import AgentCommittee
from quant.tax_optimizer import recommend_tax_loss_harvest
from quant.analytics.index_rebalancing import screen_inclusion_candidates,rebalance_exit_signal
from quant.analytics.supply_chain import SupplyChainGraph
from quant.kelly import dynamic_kelly

def good_features():
    return {"valuation":90,"roe":90,"balance_sheet":85,"consensus":90,"trend":90,"flow":85,"bollinger":80,"momentum":90,"report_conviction":90,"news_sentiment":85,"filing_risk_cleared":True,"max_correlation":.4,"vix":18}

def test_committee_approval_and_veto():
    c=AgentCommittee();assert c.decide(good_features()).final_signal=="FINAL_APPROVED_BUY"
    f=good_features();f["filing_risk_cleared"]=False;d=c.decide(f);assert d.vetoed and d.final_signal=="REJECT"

def test_tax_harvest_caps_to_excess():
    out=recommend_tax_loss_harvest(5_500_000,[{"symbol":"A","cost_basis_krw":5_000_000,"market_value_krw":3_000_000},{"symbol":"B","cost_basis_krw":4_000_000,"market_value_krw":2_500_000}],month=12)
    assert sum(x.suggested_loss_to_realize_krw for x in out)==3_000_000

def test_index_screen_and_exit():
    rows=[{"symbol":"A","market_cap":100,"adv20":100},{"symbol":"B","market_cap":200,"adv20":50},{"symbol":"C","market_cap":150,"adv20":200}]
    out=screen_inclusion_candidates(rows,top_n=2,rebalance_date="2026-12-11");assert len(out)==2 and out[0].flag=="INDEX_INCLUSION_ARBITRAGE"
    assert rebalance_exit_signal("2026-12-11","2026-12-11")=="CLOSING_AUCTION_EXIT"

def test_supply_chain_and_kelly():
    g=SupplyChainGraph({"NVDA":["SKH","HPSP"]});o=g.lagging("NVDA",5,{"SKH":.5,"HPSP":2})
    assert [x.symbol for x in o]==["SKH"]
    k=dynamic_kelly(.6,2,fraction=.25,max_weight=.1,confidence=.8);assert 0<k.portfolio_weight<=.1
