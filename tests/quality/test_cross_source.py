from quant import config
from quant.quality.cross_source import compare_sources, validate_cross_source
from tests.quality.conftest import make_records

CFG = config.quality_config()


def test_agreeing_sources_produce_no_mismatch():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ], source="primary")
    secondary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.1, "high": 105.0, "low": 98.0, "close": 102.05, "volume": 10100},
    ], source="secondary")
    comparison = compare_sources(primary, secondary, CFG)
    assert not comparison.iloc[0]["mismatch"]

    result = validate_cross_source(primary, secondary, "korea", CFG)
    assert result.passed
    assert result.mandatory


def test_disagreeing_sources_are_flagged_as_mismatch():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ], source="primary")
    secondary = make_records([
        # close off by 5% -- well beyond the 0.5% price tolerance
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 107.5, "volume": 10000},
    ], source="secondary")
    result = validate_cross_source(primary, secondary, "korea", CFG)
    assert not result.passed
    assert any("SOURCE_MISMATCH" in i.message for i in result.issues)


def test_no_secondary_source_is_skipped_not_failed_by_default():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000},
    ])
    result = validate_cross_source(primary, None, "korea", CFG)
    assert result.passed
    assert not result.mandatory
    assert result.details["secondary_available"] is False


def test_mismatch_near_corporate_action_gets_wider_tolerance():
    primary = make_records([
        {"symbol": "A", "date": "2026-08-04", "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0, "volume": 10000},
    ], source="primary")
    # a 2% difference right around a split date -- within the widened tolerance
    secondary = make_records([
        {"symbol": "A", "date": "2026-08-04", "open": 50.5, "high": 51.5, "low": 49.5, "close": 50.9, "volume": 10000},
    ], source="secondary")
    ca_dates = {"A": {__import__("pandas").Timestamp("2026-08-04")}}
    comparison = compare_sources(primary, secondary, CFG, ca_dates)
    assert not comparison.iloc[0]["mismatch"]
