"""Provider factory. All CLI entry points and the pipeline should obtain a
provider through here rather than importing a concrete class directly, so
that `--demo` (synthetic) mode is a one-line switch everywhere.
"""
from __future__ import annotations

from quant.data.base import MarketDataProvider


def get_provider(market: str, demo: bool = False) -> MarketDataProvider:
    market = market.lower()
    if market not in ("korea", "us"):
        raise ValueError(f"Unknown market: {market!r}, expected 'korea' or 'us'")

    if demo:
        from quant.data.synthetic_provider import SyntheticDataProvider
        return SyntheticDataProvider(market=market)

    if market == "korea":
        from quant.data.kr_provider import KRDataProvider
        return KRDataProvider()
    else:
        from quant.data.us_provider import USDataProvider
        return USDataProvider()
