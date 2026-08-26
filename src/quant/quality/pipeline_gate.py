"""The single entry point that ties together: providers -> Universe Engine
-> Data Quality Engine -> Canonical Data, for one market (spec sections
1-11). `validate_data.py`, `run_research.py`, and the Daily Market Scanner
should all obtain their canonical OHLCV data through `validate_market`
rather than calling a provider's `get_ohlcv_bulk` directly -- that is what
makes Fail-Closed (spec section 2) actually enforced end to end, rather
than a library that exists but nothing calls.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant import config
from quant.data.factory import get_provider, get_secondary_provider
from quant.quality.audit import AuditLog, VersionStore
from quant.quality.engine import DataQualityEngine
from quant.quality.models import DataQualityReport
from quant.universe.engine import UniverseEngine, UniverseSnapshot
from quant.utils.logging import get_logger

logger = get_logger(__name__)

_CURRENCY = {"korea": "KRW", "us": "USD"}


@dataclass
class MarketValidationResult:
    market: str
    report: DataQualityReport
    canonical_ohlcv_map: dict[str, pd.DataFrame]
    universe_snapshot: UniverseSnapshot
    provenance: list


def validate_market(
    market: str,
    demo: bool = True,
    as_of: str | None = None,
    lookback_days: int = 400,
    use_secondary: bool = True,
) -> MarketValidationResult:
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    provider = get_provider(market, demo=demo)
    secondary = get_secondary_provider(market, demo=demo, primary=provider) if use_secondary else None

    universe_engine = UniverseEngine(market, provider)
    snapshot = universe_engine.build(as_of)
    symbols = snapshot.included_symbols()

    if not symbols:
        logger.warning("Universe for market=%s as_of=%s is empty -- nothing to validate", market, as_of)

    lookback_start = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(int(lookback_days * 1.5))).strftime("%Y-%m-%d")
    primary_map = provider.get_ohlcv_bulk(symbols, lookback_start, as_of)
    secondary_map = secondary.get_ohlcv_bulk(symbols, lookback_start, as_of) if secondary else None

    symbols_info = provider.list_symbols(as_of)
    listing_dates = {s.symbol: s.listing_date for s in symbols_info if s.listing_date is not None}

    db_dir = config.resolve_path(config.settings()["paths"]["db_dir"])
    version_store = VersionStore(db_dir / "data_versions.json")
    audit_log = AuditLog(db_dir / "audit_log.jsonl")

    engine = DataQualityEngine(market)
    report, canonical_map, provenance = engine.run(
        primary_map,
        source_primary=type(provider).__name__,
        currency=_CURRENCY[market],
        start=lookback_start,
        end=as_of,
        as_of=as_of,
        secondary_ohlcv_map=secondary_map,
        source_secondary=type(secondary).__name__ if secondary else None,
        listing_dates=listing_dates,
        version_store=version_store,
        audit_log=audit_log,
    )

    return MarketValidationResult(
        market=market, report=report, canonical_ohlcv_map=canonical_map,
        universe_snapshot=snapshot, provenance=provenance,
    )
