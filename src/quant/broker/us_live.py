"""US Live Broker -- INTERFACE-ONLY STUB (spec sections 23-25).

Mirrors `broker/kr_live.py` exactly, as the future integration point for a
real US broker (e.g. Alpaca, Interactive Brokers). See that file's
docstring for the three independent layers that keep this from ever placing
a real order.
"""
from __future__ import annotations

from quant import config
from quant.broker.base import BrokerInterface


class USLiveBroker(BrokerInterface):
    market = "us"
    is_live = True

    def __init__(self, *args, **kwargs):
        if config.is_live_trading_enabled():
            raise RuntimeError(
                "Live trading is enabled but USLiveBroker is not implemented. "
                "This is an interface-only stub -- do not use in production."
            )
        raise NotImplementedError(
            "USLiveBroker is an interface stub for future real-broker integration "
            "(e.g. Alpaca, Interactive Brokers). Live trading is disabled by design "
            "in this codebase; see ARCHITECTURE.md 'Safety'."
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
