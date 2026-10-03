"""Broker gateway with mock mode as the mandatory default."""
from __future__ import annotations
from dataclasses import dataclass
import os
import math

@dataclass(frozen=True)
class OrderResult:
    accepted:bool
    mode:str
    broker:str
    symbol:str
    side:str
    quantity:int
    limit_price:float
    order_id:str|None=None
    message:str=""

class BrokerGateway:
    def __init__(self,broker:str,mock_mode:bool=True):
        self.broker=broker.lower(); self.mock_mode=bool(mock_mode)
        if self.broker not in {"kis","alpaca"}: raise ValueError("broker must be kis or alpaca")
        if not self.mock_mode and os.getenv("LIVE_TRADING","false").lower()!="true":
            raise RuntimeError("LIVE_TRADING is disabled")
    @staticmethod
    def quantity_for_weight(cash:float,weight:float,price:float)->int:
        if min(cash,price)<=0 or weight<0:return 0
        return max(0,int(math.floor(cash*weight/price)))
    def submit_limit(self,symbol:str,side:str,quantity:int,limit_price:float,approved:bool=False)->OrderResult:
        if quantity<=0 or limit_price<=0:return OrderResult(False,"MOCK" if self.mock_mode else "LIVE",self.broker,symbol,side,quantity,limit_price,message="invalid order")
        if not approved:return OrderResult(False,"MOCK" if self.mock_mode else "LIVE",self.broker,symbol,side,quantity,limit_price,message="human approval required")
        if self.mock_mode:return OrderResult(True,"MOCK",self.broker,symbol,side,quantity,limit_price,order_id=f"MOCK-{self.broker}-{symbol}")
        raise RuntimeError("Live broker HTTP transport is intentionally not enabled in this research build")
