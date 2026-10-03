"""Leader-to-supply-chain lagging opportunity detector."""
from __future__ import annotations
from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class SupplyChainOpportunity:
    leader:str
    symbol:str
    leader_move_pct:float
    follower_move_pct:float
    reflection_ratio:float
    signal:str
    def to_dict(self):return asdict(self)

class SupplyChainGraph:
    def __init__(self,mapping=None):self.mapping={k:list(v) for k,v in (mapping or {}).items()}
    def add(self,leader,followers):self.mapping.setdefault(leader,[]).extend(x for x in followers if x not in self.mapping.get(leader,[]))
    def lagging(self,leader,leader_move_pct,follower_moves,*,leader_threshold=4.0,max_reflection_ratio=.20):
        if float(leader_move_pct)<leader_threshold:return []
        out=[]
        for symbol in self.mapping.get(leader,[]):
            move=float(follower_moves.get(symbol,0.0));ratio=move/float(leader_move_pct) if leader_move_pct else 0.
            if ratio<max_reflection_ratio:out.append(SupplyChainOpportunity(leader,symbol,float(leader_move_pct),move,ratio,"SUPPLY_CHAIN_LAGGING_OPPORTUNITY"))
        return out
