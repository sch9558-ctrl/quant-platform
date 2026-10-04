"""Compatibility facade over the authoritative paper-broker ledger.

The previous implementation maintained a second cash/position/fill ledger with
its own cost assumptions. That could disagree with KoreaPaperBroker/
USPaperBroker, whose state is used by production RiskGuard. This facade keeps
legacy research call sites working while delegating all account state and
orders to the production paper broker.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import tempfile

import pandas as pd

from quant.broker.base import Fill, OrderRejection
from quant.broker.kr_paper import KoreaPaperBroker
from quant.broker.us_paper import USPaperBroker


class PaperTrader:
    def __init__(
        self,
        initial_cash: float,
        *,
        currency="KRW",
        buy_slippage=None,
        sell_slippage=None,
        commission_rate=None,
        sell_tax_rate=None,
        state_path: str | Path | None = None,
    ):
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        overrides = {
            "buy_slippage": buy_slippage,
            "sell_slippage": sell_slippage,
            "commission_rate": commission_rate,
            "sell_tax_rate": sell_tax_rate,
        }
        supplied = [name for name, value in overrides.items() if value is not None]
        if supplied:
            raise ValueError(
                "PaperTrader cost overrides are retired; the shared CostModel "
                f"is authoritative ({', '.join(supplied)} supplied)"
            )
        self.initial_cash=float(initial_cash)
        self.currency=str(currency).upper()
        self.market="korea" if self.currency=="KRW" else "us"
        self._tmpdir = None
        if state_path is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="quant-paper-compat-")
            state_path = Path(self._tmpdir.name) / f"paper_{self.market}.json"
        else:
            state_path = Path(state_path)
        broker_cls = KoreaPaperBroker if self.market=="korea" else USPaperBroker
        self._broker = broker_cls(
            initial_capital=self.initial_cash,
            state_path=state_path,
        )

    @property
    def cash(self) -> float:
        return float(self._broker.get_cash())

    @property
    def positions(self):
        return self._broker.get_positions()

    @property
    def fills(self):
        return self._broker.get_fill_history()

    @property
    def equity_history(self):
        curve=self._broker.get_equity_curve()
        return list(zip(curve.index, curve.values))

    def buy(self, symbol, quantity, price, *, timestamp=None):
        fill=self._broker.submit_order(
            str(symbol),"buy",float(quantity),float(price),reason="paper_compat_buy"
        )
        if isinstance(fill,OrderRejection):
            raise ValueError("; ".join(fill.reasons) or "paper order rejected")
        return fill

    def sell(self, symbol, quantity, price, *, timestamp=None):
        fill=self._broker.submit_order(
            str(symbol),"sell",float(quantity),float(price),reason="paper_compat_sell"
        )
        if isinstance(fill,OrderRejection):
            raise ValueError("; ".join(fill.reasons) or "paper order rejected")
        return fill

    def equity(self, marks=None):
        return float(self._broker.get_account_value(marks or {}))

    def mark(self, marks, *, timestamp=None):
        as_of=pd.Timestamp(timestamp) if timestamp is not None else None
        return float(self._broker.record_daily_equity(marks or {},as_of=as_of))

    def _closed_trade_pnls(self) -> list[float]:
        positions={}
        pnls=[]
        for fill in self._broker.get_fill_history():
            qty=float(fill.quantity)
            if fill.side=="buy":
                old_qty,old_cost=positions.get(fill.symbol,(0.0,0.0))
                new_qty=old_qty+qty
                avg=(old_qty*old_cost+qty*float(fill.price))/new_qty if new_qty else 0.0
                positions[fill.symbol]=(new_qty,avg)
            elif fill.side=="sell":
                old_qty,old_cost=positions.get(fill.symbol,(0.0,0.0))
                realized=(float(fill.price)-old_cost)*qty-float(fill.commission)-float(fill.tax_or_fee)
                pnls.append(realized)
                remaining=max(0.0,old_qty-qty)
                if remaining:
                    positions[fill.symbol]=(remaining,old_cost)
                else:
                    positions.pop(fill.symbol,None)
        return pnls

    def summary(self, marks=None):
        eq=self.equity(marks)
        pnls=self._closed_trade_pnls()
        gains=sum(x for x in pnls if x>0)
        losses=abs(sum(x for x in pnls if x<0))
        win_rate=(sum(x>0 for x in pnls)/len(pnls)) if pnls else None
        profit_factor=gains/losses if losses>0 else (math.inf if gains>0 else None)
        curve=self._broker.get_equity_curve()
        mdd=float((curve/curve.cummax()-1).min()) if len(curve) else 0.0
        return {
            "currency":self.currency,
            "initial_cash":self.initial_cash,
            "cash":self.cash,
            "equity":eq,
            "total_return_pct":(eq/self.initial_cash-1)*100,
            "realized_pnl":sum(pnls),
            "closed_trades":len(pnls),
            "win_rate":win_rate,
            "profit_factor":profit_factor,
            "max_drawdown":mdd,
            "positions":{
                symbol:{
                    "symbol":position.symbol,
                    "quantity":position.quantity,
                    "avg_cost":position.avg_cost,
                }
                for symbol,position in self._broker.get_positions().items()
            },
            "ledger_authority":type(self._broker).__name__,
        }

    def write_summary(self, path, marks=None):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(
            json.dumps(self.summary(marks),ensure_ascii=False,indent=2,default=str),
            encoding="utf-8",
        )
        return path
