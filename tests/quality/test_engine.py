import pandas as pd

from quant.quality.engine import DataQualityEngine
from quant.quality.gate import may_proceed


def _wide(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


def test_clean_data_passes_end_to_end():
    dates = pd.bdate_range("2026-08-03", periods=8)
    ohlcv = _wide([
        {"date": d, "open": 100 + i * 0.1, "high": 101 + i * 0.1, "low": 99 + i * 0.1, "close": 100 + i * 0.1, "volume": 10000}
        for i, d in enumerate(dates)
    ])
    engine = DataQualityEngine("korea")
    report, canonical_map, provenance = engine.run(
        {"AAA": ohlcv}, source_primary="test_primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
    )
    assert report.overall_status == "PASS"
    assert report.mandatory_validation_pass_rate == 100.0
    allowed, _ = may_proceed(report)
    assert allowed
    assert "AAA" in canonical_map
    assert len(canonical_map["AAA"]) == len(ohlcv)


def test_missing_session_fails_closed_and_returns_no_canonical_data():
    dates = [d for d in pd.bdate_range("2026-08-03", periods=8) if d != pd.Timestamp("2026-08-06")]
    ohlcv = _wide([
        {"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10000} for d in dates
    ])
    engine = DataQualityEngine("korea")
    report, canonical_map, provenance = engine.run(
        {"AAA": ohlcv}, source_primary="test_primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
    )
    assert report.overall_status == "FAIL"
    assert report.mandatory_validation_pass_rate == 0.0
    allowed, reason = may_proceed(report)
    assert not allowed
    assert "DATA VALIDATION FAILED" in reason
    assert canonical_map == {}


def test_ohlc_violation_fails_closed():
    dates = pd.bdate_range("2026-08-03", periods=8)
    rows = [
        {"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10000} for d in dates
    ]
    rows[3]["high"] = 50  # inject an OHLC violation (high < low)
    ohlcv = _wide(rows)
    engine = DataQualityEngine("korea")
    report, canonical_map, provenance = engine.run(
        {"AAA": ohlcv}, source_primary="test_primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
    )
    assert report.overall_status == "FAIL"
    assert canonical_map == {}


def test_source_mismatch_fails_closed_but_agreeing_secondary_passes():
    dates = pd.bdate_range("2026-08-03", periods=8)
    primary_rows = [{"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10000} for d in dates]
    primary = _wide(primary_rows)
    secondary = _wide(primary_rows)  # identical -> agrees

    engine = DataQualityEngine("korea")
    report, canonical_map, provenance = engine.run(
        {"AAA": primary}, source_primary="primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
        secondary_ohlcv_map={"AAA": secondary}, source_secondary="secondary",
    )
    assert report.overall_status == "PASS"

    bad_secondary_rows = [dict(r) for r in primary_rows]
    bad_secondary_rows[0]["close"] = 200  # wildly different -> mismatch
    bad_secondary = _wide(bad_secondary_rows)
    report2, canonical_map2, _ = engine.run(
        {"AAA": primary}, source_primary="primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
        secondary_ohlcv_map={"AAA": bad_secondary}, source_secondary="secondary",
    )
    assert report2.overall_status == "FAIL"
    assert canonical_map2 == {}


def test_data_integrity_score_is_never_reported_as_100_percent_accuracy_claim():
    # data_integrity_score is an informational continuous metric and must
    # be independent from mandatory_validation_pass_rate (which is always
    # exactly 0.0 or 100.0) -- this test just asserts the two fields exist
    # and can legitimately differ, guarding against them being merged later.
    dates = pd.bdate_range("2026-08-03", periods=8)
    ohlcv = _wide([{"date": d, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10000} for d in dates])
    engine = DataQualityEngine("korea")
    report, _, _ = engine.run(
        {"AAA": ohlcv}, source_primary="test_primary", currency="KRW",
        start="2026-08-03", end="2026-08-12", as_of="2026-08-12",
    )
    assert report.mandatory_validation_pass_rate in (0.0, 100.0)
    assert 0.0 <= report.data_integrity_score <= 1.0
