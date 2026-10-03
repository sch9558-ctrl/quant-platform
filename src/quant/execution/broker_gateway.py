"""Approval-gated broker gateway.

Live order transmission is intentionally disabled. This produces deterministic
mock order intents for human review.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
import uuid

@dataclass(frozen=True)
class OrderIntent:
    intent_id:str
    broker:str
    symbol:str
    side:str
    quantity:int
    limit_price:float
    mock_mode:bool
    status:str
    def to_dict(self):return asdict(self)

class BrokerGateway:
    def __init__(self,broker,*,mock_mode=True):
        self.broker=str(broker);self.mock_mode=bool(mock_mode)
        if not self.mock_mode:raise RuntimeError("live order transmission is disabled; use mock_mode=True")
    @staticmethod
    def quantity_from_weight(cash,weight,limit_price):
        if cash<0 or not 0<=weight<=1 or limit_price<=0:raise ValueError("invalid sizing inputs")
        return max(0,int(float(cash)*float(weight)/float(limit_price)))
    def create_limit_intent(self,symbol,side,quantity,limit_price):
        if str(side).upper() not in {"BUY","SELL"} or quantity<=0 or limit_price<=0:raise ValueError("invalid order")
        return OrderIntent(uuid.uuid4().hex,self.broker,str(symbol),str(side).upper(),int(quantity),float(limit_price),True,"PENDING_HUMAN_APPROVAL")
