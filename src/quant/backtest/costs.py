"""Transaction cost model (spec section 9), shared by the backtester
(applied to every simulated fill) and the daily scanner (used only to show
an *estimated* round-trip cost per candidate, informational).

Korea: commission (both sides) + securities transaction tax (sell side
only, rate depends on KOSPI/KOSDAQ/ETF) + slippage (both sides).
US: commission (both sides, usually 0 today) + SEC fee + FINRA TAF (sell
side only, tiny) + slippage (both sides).
"""
from __future__ import annotations

from dataclasses import dataclass

from quant import config


@dataclass
class Fill:
    notional: float
    commission: float
    tax_or_fee: float
    slippage_cost: float

    @property
    def total_cost(self) -> float:
        return self.commission + self.tax_or_fee + self.slippage_cost

    @property
    def total_cost_bps(self) -> float:
        return 10_000 * self.total_cost / self.notional if self.notional else 0.0


class CostModel:
    def __init__(self, market: str):
        assert market in ("korea", "us")
        self.market = market
        self._cfg = config.costs_config()

    # -- per-fill cost application (used by the backtester) ---------------
    def apply(self, notional: float, is_sell: bool, asset_type: str = "equity", exchange: str | None = None) -> Fill:
        notional = abs(notional)
        if self.market == "korea":
            return self._apply_korea(notional, is_sell, asset_type, exchange)
        return self._apply_us(notional, is_sell)

    def _apply_korea(self, notional: float, is_sell: bool, asset_type: str, exchange: str | None) -> Fill:
        c = self._cfg["korea"]
        commission = max(notional * c["commission_rate"], c.get("min_commission_krw", 0))
        tax = 0.0
        if is_sell:
            if asset_type == "etf":
                tax = notional * c["securities_transaction_tax"].get("etf", 0.0)
            elif (exchange or "").upper() == "KOSDAQ":
                tax = notional * c["securities_transaction_tax"]["kosdaq"]
            else:
                tax = notional * c["securities_transaction_tax"]["kospi"]
        slippage = notional * (c["slippage_bps"] / 10_000)
        return Fill(notional=notional, commission=commission, tax_or_fee=tax, slippage_cost=slippage)

    def _apply_us(self, notional: float, is_sell: bool) -> Fill:
        c = self._cfg["us"]
        commission = max(notional * c["commission_rate"], c.get("min_commission_usd", 0))
        fee = 0.0
        if is_sell:
            fee = notional * c.get("sec_fee_rate", 0.0)
            # FINRA TAF is per-share; approximate using an assumed average
            # share price of 50 when only notional is known (real backtests
            # should call apply_us_per_share when share count is available).
            fee += (notional / 50.0) * c.get("finra_taf_per_share", 0.0)
        slippage = notional * (c["slippage_bps"] / 10_000)
        return Fill(notional=notional, commission=commission, tax_or_fee=fee, slippage_cost=slippage)

    def apply_us_per_share(self, shares: float, price: float, is_sell: bool) -> Fill:
        """More precise US cost calc when share count is known (FINRA TAF is
        genuinely per-share, not per-dollar)."""
        c = self._cfg["us"]
        notional = abs(shares) * price
        commission = max(notional * c["commission_rate"], c.get("min_commission_usd", 0))
        fee = 0.0
        if is_sell:
            fee = notional * c.get("sec_fee_rate", 0.0) + abs(shares) * c.get("finra_taf_per_share", 0.0)
        slippage = notional * (c["slippage_bps"] / 10_000)
        return Fill(notional=notional, commission=commission, tax_or_fee=fee, slippage_cost=slippage)

    # -- informational estimate (used by the scanner) ----------------------
    def estimate_round_trip_cost_bps(self, asset_type: str = "equity", exchange: str | None = None) -> float:
        """Estimated total cost (buy + sell) in basis points of notional,
        for display purposes on scanner candidates."""
        buy = self.apply(1_000_000, is_sell=False, asset_type=asset_type, exchange=exchange)
        sell = self.apply(1_000_000, is_sell=True, asset_type=asset_type, exchange=exchange)
        return buy.total_cost_bps + sell.total_cost_bps

    def fill_price_rule(self) -> str:
        return self._cfg["general"]["fill_price"]

    def fill_delay_bars(self) -> int:
        return self._cfg["general"]["fill_delay_bars"]

    def max_participation_of_volume(self) -> float:
        return self._cfg["general"]["max_participation_of_volume"]
