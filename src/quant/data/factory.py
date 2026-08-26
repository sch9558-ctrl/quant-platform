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


def get_secondary_provider(market: str, demo: bool = False, primary=None):
    """A second, independent data source for Cross-Source Validation (spec
    section 9) -- never used to build a universe or drive a strategy on
    its own, only to compare against the Primary provider's values.

    Returns `None` if no secondary source is configured/available; callers
    (the Data Quality Engine, `validate_data.py`) must treat a `None`
    secondary as "comparison skipped", not as a validation failure, unless
    `config/quality.yaml`'s `cross_source.require_secondary` is set True.
    """
    market = market.lower()
    if market not in ("korea", "us"):
        raise ValueError(f"Unknown market: {market!r}, expected 'korea' or 'us'")

    if demo:
        from quant.data.synthetic_provider import SyntheticDataProvider
        from quant.data.synthetic_secondary_provider import SyntheticSecondaryProvider
        primary = primary if isinstance(primary, SyntheticDataProvider) else SyntheticDataProvider(market=market)
        return SyntheticSecondaryProvider(primary)

    if market == "korea":
        from quant.data.kr_secondary_provider import KRSecondaryProvider
        return KRSecondaryProvider()
    else:
        from quant.data.us_secondary_provider import USSecondaryProvider
        return USSecondaryProvider()
