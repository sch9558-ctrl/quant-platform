"""Index-rebalancing event screening primitives."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import pandas as pd

@dataclass(frozen=True)
class IndexCandidate:
    symbol:str
    score:float
    flag:str
    rebalance_date:str|None
    def to_dict(self):return asdict(self)

def screen_inclusion_candidates(rows,*,top_n=10,announcement_date=None,rebalance_date=None):
    df=pd.DataFrame(rows)
    if df.empty:return []
    for c in ("market_cap","adv20"):
        if c not in df:raise ValueError(f"missing {c}")
        df[c]=pd.to_numeric(df[c],errors="coerce").fillna(0)
    cap_rank=df["market_cap"].rank(pct=True);liq_rank=df["adv20"].rank(pct=True);df["score"]=.65*cap_rank+.35*liq_rank
    df=df.sort_values("score",ascending=False).head(int(top_n))
    return [IndexCandidate(str(row["symbol"]),float(row["score"]),"INDEX_INCLUSION_ARBITRAGE",None if rebalance_date is None else str(pd.Timestamp(rebalance_date).date())) for _,row in df.iterrows()]

def rebalance_exit_signal(as_of,rebalance_date):
    return "CLOSING_AUCTION_EXIT" if pd.Timestamp(as_of).normalize()>=pd.Timestamp(rebalance_date).normalize() else "HOLD_EVENT"
