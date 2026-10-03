"""Rule-based index inclusion candidate and rebalance event flags."""
from __future__ import annotations
import pandas as pd

def screen_inclusion_candidates(frame:pd.DataFrame,index_name:str,top_n:int=20)->pd.DataFrame:
    required={"symbol","avg_market_cap","avg_trading_value"}
    if not required.issubset(frame.columns): raise ValueError(f"missing columns: {sorted(required-set(frame.columns))}")
    df=frame.copy()
    df["cap_pct"]=df["avg_market_cap"].rank(pct=True)
    df["liq_pct"]=df["avg_trading_value"].rank(pct=True)
    df["inclusion_score"]=0.65*df["cap_pct"]+0.35*df["liq_pct"]
    df["event_flag"]="INDEX_INCLUSION_ARBITRAGE"
    df["index_name"]=index_name
    return df.sort_values("inclusion_score",ascending=False).head(top_n)

def rebalance_exit_signal(as_of,rebalance_date)->str:
    return "REBALANCE_CLOSE_AUCTION_EXIT" if pd.Timestamp(as_of).normalize()>=pd.Timestamp(rebalance_date).normalize() else "HOLD"
