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
from quant.quality.gate import may_proceed
from quant.quality.models import DataQualityReport
from quant.universe.engine import UniverseEngine, UniverseSnapshot
from quant.utils.calendar import default_as_of
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
    provider=None,
) -> MarketValidationResult:
    as_of = as_of or default_as_of(market)
    provider = provider or get_provider(market, demo=demo)
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


@dataclass
class GatedScanResult:
    """The result of running the Daily Market Scanner *through* the
    Fail-Closed gate. `blocked=True` means the Data Quality Engine did not
    pass its mandatory checks for this market/day -- `scan` is then None on
    purpose, and no caller downstream of this function (strategy
    evaluation, candidate ranking, paper-trading order generation) should
    ever run. The dashboard must still be told about this result (spec:
    "Research 실패 != Dashboard 배포 실패" -- research failing is not the
    same as failing to deploy the dashboard); it just renders a clear
    DATA VALIDATION FAILED state instead of candidates."""
    market: str
    as_of: str
    validation: MarketValidationResult
    scan: object | None
    blocked: bool
    block_reason: str


def run_gated_scan(
    market: str,
    provider=None,
    as_of: str | None = None,
    demo: bool = True,
    lookback_days: int = 400,
    top_n: int = 20,
    use_secondary: bool = True,
) -> GatedScanResult:
    """The single entry point every daily-candidate-generating caller
    (`run_scan.py`, the research pipeline, `run_paper.py`) should use
    instead of instantiating `DailyScanner` directly against a raw
    provider. Runs the Data Quality Engine first; only on a PASS does it
    feed the resulting *canonical* (validated, consensus-built) OHLCV data
    and the same universe snapshot into the scanner -- so the scanner never
    re-fetches raw, unvalidated data behind the gate's back, and never
    builds the universe twice."""
    from quant.scanner.scanner import DailyScanner  # local import: avoids a
    # scanner<->quality import cycle (scanner.py does not import this module).

    as_of = as_of or default_as_of(market)
    validation = validate_market(
        market, demo=demo, as_of=as_of, lookback_days=lookback_days,
        use_secondary=use_secondary, provider=provider,
    )
    allowed, reason = may_proceed(validation.report)
    if not allowed:
        logger.error(reason)
        return GatedScanResult(
            market=market, as_of=as_of, validation=validation,
            scan=None, blocked=True, block_reason=reason,
        )

    scanner = DailyScanner(market, provider or get_provider(market, demo=demo))
    scan = scanner.run(
        as_of=as_of, lookback_days=lookback_days, top_n=top_n,
        universe_snapshot=validation.universe_snapshot,
        ohlcv_map=validation.canonical_ohlcv_map,
    )
    return GatedScanResult(
        market=market, as_of=as_of, validation=validation,
        scan=scan, blocked=False, block_reason=reason,
    )
