"""Broker Interface (spec sections 23-24-25).

Adapter pattern: every concrete broker (Korea/US, Paper/Live) implements
this same interface, so nothing above this layer (CLI, dashboard, future
automated scheduling) is coupled to a specific brokerage's API.

SAFETY: `is_live` is a class attribute, not a constructor argument -- a
caller cannot accidentally "turn on" live trading by passing a flag. Only
`KoreaLiveBroker`/`USLiveBroker` set it True, and both of those raise on
every order method regardless (see broker/kr_live.py, broker/us_live.py),
and `quant.config.is_live_trading_enabled()` is hardcoded False in this
shipped code -- three independent layers all have to be deliberately
changed by a human before any live order could ever be attempted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_cost  # updated by mark_to_market with live price


@dataclass
class Fill:
    fill_id: str
    symbol: str
    side: str          # "buy" | "sell"
    quantity: float
    price: float
    commission: float
    tax_or_fee: float
    filled_at: pd.Timestamp
    reason: str = ""    # e.g. "rebalance", "stop_loss", "manual"


@dataclass
class OrderRejection:
    symbol: str
    requested_quantity: float
    reasons: list[str] = field(default_factory=list)


class BrokerInterface(ABC):
    market: str
    is_live: bool = False

    @abstractmethod
    def get_cash(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]: ...

    @abstractmethod
    def get_account_value(self, prices: dict[str, float] | None = None) -> float: ...

    @abstractmethod
    def submit_order(
        self, symbol: str, side: str, quantity: float, price: float, sector: str | None = None,
        reason: str = "manual",
    ) -> Fill | OrderRejection: ...

    @abstractmethod
    def get_fill_history(self) -> list[Fill]: ...

    @abstractmethod
    def get_equity_curve(self) -> pd.Series: ...
