"""Supply-chain leader/laggard propagation graph."""
from __future__ import annotations
from dataclasses import dataclass

DEFAULT_GRAPH={"NVDA":["000660","042700","007660"],"AAPL":["011070","090460"]}

@dataclass(frozen=True)
class SupplyChainSignal:
    leader:str
    follower:str
    leader_return:float
    follower_reflection:float
    signal:str

def lagging_opportunities(leader:str,leader_return:float,follower_returns:dict[str,float],graph=None,leader_threshold:float=0.04,reflection_limit:float=0.20):
    graph=graph or DEFAULT_GRAPH
    if leader_return<leader_threshold:return []
    out=[]
    for follower in graph.get(leader,[]):
        r=float(follower_returns.get(follower,0.0))
        reflection=abs(r/leader_return) if leader_return else 1.0
        if reflection<reflection_limit:
            out.append(SupplyChainSignal(leader,follower,leader_return,reflection,"SUPPLY_CHAIN_LAGGING_OPPORTUNITY"))
    return out
