from quant import config
from quant.quality.canonical import build_canonical
from quant.quality.cross_source import compare_sources
from tests.quality.conftest import make_records

CFG = config.quality_config()


def test_agreeing_row_is_kept_with_primary_as_canonical_source():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ], source="primary")
    secondary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.1, "high": 105.0, "low": 98.0, "close": 102.05, "volume": 10100},
    ], source="secondary")
    comparison = compare_sources(primary, secondary, CFG)

    canonical, provenance = build_canonical(primary, secondary, comparison, "primary", "secondary")
    assert len(canonical) == 1
    assert provenance[0].canonical_source == "primary"
    assert provenance[0].validation == "PASS"


def test_mismatched_row_is_excluded_from_canonical():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ], source="primary")
    secondary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 130.0, "volume": 10000},
    ], source="secondary")
    comparison = compare_sources(primary, secondary, CFG)

    canonical, provenance = build_canonical(primary, secondary, comparison, "primary", "secondary")
    assert len(canonical) == 0
    assert provenance[0].validation == "SOURCE_MISMATCH"
    assert provenance[0].canonical_source is None


def test_no_secondary_available_uses_primary_as_is():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ], source="primary")
    canonical, provenance = build_canonical(primary, None, None, "primary", None)
    assert len(canonical) == 1
    assert provenance[0].validation == "SECONDARY_UNAVAILABLE"
    assert provenance[0].canonical_source == "primary"


def test_provenance_is_never_a_plain_average():
    # spec explicitly forbids "단순 평균" -- assert the canonical close is
    # exactly the primary value, not a blend of primary/secondary.
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 100.0, "volume": 10000},
    ], source="primary")
    secondary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.2, "high": 105.0, "low": 98.0, "close": 100.3, "volume": 10000},
    ], source="secondary")
    comparison = compare_sources(primary, secondary, CFG)
    canonical, _ = build_canonical(primary, secondary, comparison, "primary", "secondary")
    assert canonical.iloc[0]["close"] == 100.0  # not (100.0+100.3)/2
