from __future__ import annotations

from pathlib import Path

from quant.broker.paper_base import PaperBrokerBase
from quant.risk.manager import RiskManager

DEFAULT_INITIAL_CAPITAL_KRW = 100_000_000.0


class KoreaPaperBroker(PaperBrokerBase):
    def __init__(self, initial_capital: float = DEFAULT_INITIAL_CAPITAL_KRW,
                 state_path: Path | None = None, risk_manager: RiskManager | None = None):
        super().__init__(market="korea", initial_capital=initial_capital,
                          state_path=state_path, risk_manager=risk_manager)
