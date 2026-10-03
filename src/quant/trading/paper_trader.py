"""Persistent paper-trading ledger with slippage and fee accounting."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json
import pandas as pd

@dataclass
class Position:
    symbol:str; quantity:int; avg_cost:float; market:str="korea"

class PaperTrader:
    def __init__(self,initial_cash:float=10_000_000,slippage:float=0.001,fee_rate:float=0.00015,tax_rate:float=0.0,ledger_path:str|Path|None=None):
        self.initial_cash=float(initial_cash); self.cash=float(initial_cash); self.slippage=float(slippage); self.fee_rate=float(fee_rate); self.tax_rate=float(tax_rate)
        self.positions={}; self.trades=[]; self.equity_curve=[]; self.ledger_path=Path(ledger_path) if ledger_path else None
    def buy(self,symbol:str,quantity:int,market_price:float,market:str="korea"):
        fill=float(market_price)*(1+self.slippage); cost=fill*quantity; fee=cost*self.fee_rate; total=cost+fee
        if quantity<=0 or total>self.cash: raise ValueError("insufficient paper cash or invalid quantity")
        old=self.positions.get(symbol); old_q=old.quantity if old else 0; old_cost=old.avg_cost*old_q if old else 0
        self.positions[symbol]=Position(symbol,old_q+quantity,(old_cost+cost)/(old_q+quantity),market)
        self.cash-=total; self.trades.append({"side":"BUY","symbol":symbol,"quantity":quantity,"fill":fill,"fee":fee})
        return fill
    def sell(self,symbol:str,quantity:int,market_price:float):
        pos=self.positions.get(symbol)
        if pos is None or quantity<=0 or quantity>pos.quantity: raise ValueError("invalid paper sell")
        fill=float(market_price)*(1-self.slippage); gross=fill*quantity; fee=gross*self.fee_rate; tax=max(gross-pos.avg_cost*quantity,0)*self.tax_rate
        self.cash+=gross-fee-tax; pnl=(fill-pos.avg_cost)*quantity-fee-tax
        pos.quantity-=quantity
        if pos.quantity==0:self.positions.pop(symbol)
        self.trades.append({"side":"SELL","symbol":symbol,"quantity":quantity,"fill":fill,"fee":fee,"tax":tax,"pnl":pnl})
        return fill
    def mark(self,date,prices:dict[str,float]):
        equity=self.cash+sum(p.quantity*float(prices.get(s,p.avg_cost)) for s,p in self.positions.items())
        self.equity_curve.append({"date":str(pd.Timestamp(date).date()),"equity":float(equity)}); return float(equity)
    def summary(self):
        sells=[t for t in self.trades if t["side"]=="SELL"]; pnls=[t["pnl"] for t in sells]
        eq=pd.Series([x["equity"] for x in self.equity_curve],dtype=float)
        mdd=float((eq/eq.cummax()-1).min()) if len(eq) else 0.0
        gains=sum(x for x in pnls if x>0); losses=-sum(x for x in pnls if x<0)
        return {"cash":self.cash,"positions":{s:asdict(p) for s,p in self.positions.items()},"cumulative_return":(float(eq.iloc[-1])/self.initial_cash-1) if len(eq) else 0.0,"win_rate":sum(x>0 for x in pnls)/len(pnls) if pnls else None,"profit_factor":gains/losses if losses>0 else None,"max_drawdown":mdd,"n_closed_trades":len(sells)}
    def write_summary(self,path="dashboard/data/paper_trading_summary.json"):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(self.summary(),ensure_ascii=False,indent=2),encoding="utf-8"); return p
