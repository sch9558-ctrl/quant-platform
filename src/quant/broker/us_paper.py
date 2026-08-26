from __future__ import annotations

from pathlib import Path

from quant.broker.paper_base import PaperBrokerBase
from quant.risk.manager import RiskManager

DEFAULT_INITIAL_CAPITAL_USD = 100_000.0


class USPaperBroker(PaperBrokerBase):
    def __init__(self, initial_capital: float = DEFAULT_INITIAL_CAPITAL_USD,
                 state_path: Path | None = None, risk_manager: RiskManager | None = None):
        super().__init__(market="us", initial_capital=initial_capital,
                          state_path=state_path, risk_manager=risk_manager)
