"""Korea Live Broker -- INTERFACE-ONLY STUB (spec sections 23-25).

This class exists purely to show where a real brokerage integration (e.g.
Korea Investment & Securities' Open API) would plug in later. It does not,
and structurally cannot, place a real order:

  1. `quant.config.is_live_trading_enabled()` is hardcoded False in shipped
     code (`quant/config.py`'s `_LIVE_TRADING_HARD_LOCK`).
  2. This class's `__init__` re-checks that flag and raises if anyone tries
     to instantiate it while live trading is enabled.
  3. Every order method raises `NotImplementedError` unconditionally, as a
     third, independent layer of defense.

Wiring up a real broker here is a deliberate, future, human-initiated task
-- not something this codebase does on its own.
"""
from __future__ import annotations

from quant import config
from quant.broker.base import BrokerInterface


class KoreaLiveBroker(BrokerInterface):
    market = "korea"
    is_live = True

    def __init__(self, *args, **kwargs):
        if config.is_live_trading_enabled():
            raise RuntimeError(
                "Live trading is enabled but KoreaLiveBroker is not implemented. "
                "This is an interface-only stub -- do not use in production."
            )
        raise NotImplementedError(
            "KoreaLiveBroker is an interface stub for future real-broker integration "
            "(e.g. Korea Investment & Securities Open API). Live trading is disabled "
            "by design in this codebase; see ARCHITECTURE.md 'Safety'."
        )

    def get_cash(self) -> float:
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def get_account_value(self, prices=None) -> float:
        raise NotImplementedError

    def submit_order(self, symbol, side, quantity, price, sector=None, reason="manual"):
        raise NotImplementedError("Live order submission is disabled in this codebase.")

    def get_fill_history(self):
        raise NotImplementedError

    def get_equity_curve(self):
        raise NotImplementedError
