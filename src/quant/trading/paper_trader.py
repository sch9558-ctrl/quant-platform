"""Deterministic paper-trading ledger with slippage and fee accounting."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json, math
import pandas as pd

@dataclass
class PaperPosition:
    symbol: str
    quantity: int
    avg_cost: float

@dataclass(frozen=True)
class PaperFill:
    timestamp: str
    symbol: str
    side: str
    quantity: int
    reference_price: float
    fill_price: float
    fees: float
    tax: float
    cash_after: float

class PaperTrader:
    def __init__(self, initial_cash: float, *, currency="KRW", buy_slippage=.001, sell_slippage=.001, commission_rate=.00015, sell_tax_rate=0.0):
        if initial_cash <= 0: raise ValueError("initial_cash must be positive")
        self.initial_cash=float(initial_cash); self.cash=float(initial_cash); self.currency=currency
        self.buy_slippage=float(buy_slippage); self.sell_slippage=float(sell_slippage)
        self.commission_rate=float(commission_rate); self.sell_tax_rate=float(sell_tax_rate)
        self.positions={}; self.fills=[]; self.realized_pnl=0.0; self.closed_trade_pnls=[]; self.equity_history=[]

    def _stamp(self, timestamp=None):
        return pd.Timestamp(timestamp or pd.Timestamp.now(tz="UTC")).isoformat()

    def buy(self, symbol, quantity, price, *, timestamp=None):
        if quantity <= 0 or price <= 0: raise ValueError("quantity and price must be positive")
        fill_price=float(price)*(1+self.buy_slippage); notional=fill_price*int(quantity); fees=notional*self.commission_rate
        if notional+fees > self.cash+1e-9: raise ValueError("insufficient paper cash")
        old=self.positions.get(symbol)
        if old:
            nq=old.quantity+int(quantity); avg=(old.avg_cost*old.quantity+fill_price*int(quantity))/nq
            self.positions[symbol]=PaperPosition(symbol,nq,float(avg))
        else: self.positions[symbol]=PaperPosition(symbol,int(quantity),fill_price)
        self.cash-=notional+fees
        fill=PaperFill(self._stamp(timestamp),symbol,"BUY",int(quantity),float(price),fill_price,fees,0.0,self.cash)
        self.fills.append(fill); return fill

    def sell(self, symbol, quantity, price, *, timestamp=None):
        pos=self.positions.get(symbol)
        if pos is None or quantity<=0 or quantity>pos.quantity or price<=0: raise ValueError("invalid sell quantity/price")
        fill_price=float(price)*(1-self.sell_slippage); notional=fill_price*int(quantity)
        fees=notional*self.commission_rate; tax=notional*self.sell_tax_rate; proceeds=notional-fees-tax
        pnl=(fill_price-pos.avg_cost)*int(quantity)-fees-tax
        self.realized_pnl+=pnl; self.closed_trade_pnls.append(float(pnl))
        remaining=pos.quantity-int(quantity)
        if remaining: self.positions[symbol]=PaperPosition(symbol,remaining,pos.avg_cost)
        else: del self.positions[symbol]
        self.cash+=proceeds
        fill=PaperFill(self._stamp(timestamp),symbol,"SELL",int(quantity),float(price),fill_price,fees,tax,self.cash)
        self.fills.append(fill); return fill

    def equity(self, marks=None):
        marks=marks or {}; value=self.cash
        for symbol,pos in self.positions.items(): value += pos.quantity*float(marks.get(symbol,pos.avg_cost))
        return float(value)

    def mark(self, marks, *, timestamp=None):
        eq=self.equity(marks); self.equity_history.append((self._stamp(timestamp),eq)); return eq

    def summary(self, marks=None):
        eq=self.equity(marks); gains=sum(x for x in self.closed_trade_pnls if x>0); losses=abs(sum(x for x in self.closed_trade_pnls if x<0))
        wins=sum(x>0 for x in self.closed_trade_pnls); win_rate=wins/len(self.closed_trade_pnls) if self.closed_trade_pnls else None
        pf=gains/losses if losses>0 else (math.inf if gains>0 else None)
        if self.equity_history:
            s=pd.Series([v for _,v in self.equity_history],dtype=float); mdd=float((s/s.cummax()-1).min())
        else: mdd=0.0
        return {"currency":self.currency,"initial_cash":self.initial_cash,"cash":self.cash,"equity":eq,
                "total_return_pct":(eq/self.initial_cash-1)*100,"realized_pnl":self.realized_pnl,
                "closed_trades":len(self.closed_trade_pnls),"win_rate":win_rate,"profit_factor":pf,
                "max_drawdown":mdd,"positions":{s:asdict(p) for s,p in self.positions.items()}}

    def write_summary(self, path, marks=None):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(self.summary(marks),ensure_ascii=False,indent=2,default=str),encoding="utf-8")
        return path
