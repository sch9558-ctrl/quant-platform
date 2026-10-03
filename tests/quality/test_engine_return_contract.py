"""Every exit from the Data Quality Engine returns the same three things.

`DataQualityEngine.run` is the choke point the whole Fail-Closed design
rests on, and callers unpack it:

    report, canonical_map, provenance = engine.run(...)

On 2026-10-01 the US market produced data whose schema check failed -- the
exact situation this engine exists to catch -- and the run died with
`TypeError: cannot unpack non-iterable DataQualityReport object`, because
the schema-failure branch returned the report by itself while every other
branch returned three values.

Two things made that worse than a typo. The crash happened only on the
failure path, so no amount of healthy-data testing would ever reach it. And
the exception it raised said nothing about the schema problem that caused
it, so the report blamed the market for being unreachable.

These tests exercise the shape of the contract rather than the quality
verdict, so a future early return cannot reintroduce it.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.quality.engine import DataQualityEngine
from quant.quality.models import DataQualityReport


def _frame(**over) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1100],
            "adj_close": [101.0, 102.0],
        },
        index=pd.DatetimeIndex(["2026-09-28", "2026-09-29"], name="date"),
    )
    for k, v in over.items():
        base[k] = v
    return base


def _run(engine, ohlcv_map):
    return engine.run(
        ohlcv_map,
        source_primary="TestProvider",
        currency="USD",
        start="2026-09-28",
        end="2026-09-29",
        as_of="2026-09-29",
    )


@pytest.fixture
def engine():
    return DataQualityEngine("us")


def _assert_contract(result):
    """(report, canonical_ohlcv_map, provenance) -- always, on every path."""
    assert isinstance(result, tuple), (
        f"run() returned a bare {type(result).__name__}; callers unpack three values"
    )
    assert len(result) == 3, f"expected 3 values, got {len(result)}"
    report, canonical_map, provenance = result
    assert isinstance(report, DataQualityReport)
    assert isinstance(canonical_map, dict)
    assert isinstance(provenance, list)
    return report, canonical_map, provenance


def test_healthy_data_returns_the_three_value_contract(engine):
    _assert_contract(_run(engine, {"AAA": _frame()}))


def test_a_schema_failure_returns_the_same_contract(engine):
    """The branch that crashed. A frame missing required columns is the
    engine's whole reason to exist, not an input it may die on."""
    broken = _frame().drop(columns=["volume", "close"])
    report, canonical_map, provenance = _assert_contract(_run(engine, {"AAA": broken}))
    assert report.overall_status == "FAIL"
    assert canonical_map == {}, (
        "Fail-Closed: no data may leave the engine when validation failed"
    )


def test_an_empty_input_returns_the_same_contract(engine):
    _assert_contract(_run(engine, {}))


def test_a_schema_failure_names_the_check_that_failed(engine):
    """The TypeError hid the cause. A failing report must say what broke,
    or the next person reads 'market unreachable' and looks at the network."""
    broken = _frame().drop(columns=["close"])
    report, _, _ = _assert_contract(_run(engine, {"AAA": broken}))
    failed = [c.check for c in report.mandatory_failures()]
    assert "schema" in failed, f"schema failure not reported; failures were {failed}"


def test_the_failing_report_still_carries_market_and_date(engine):
    """A blocked market is rendered from this report, so the fields the
    dashboard keys off must survive the failure path."""
    broken = _frame().drop(columns=["high"])
    report, _, _ = _assert_contract(_run(engine, {"AAA": broken}))
    assert report.market == "us"
    assert report.as_of == "2026-09-29"
    assert report.mandatory_validation_pass_rate == 0.0


def test_a_schema_failure_stops_before_the_later_checks(engine):
    """Running the remaining checks against a frame with missing columns
    produces a pile of secondary errors that bury the real one."""
    broken = _frame().drop(columns=["low", "volume"])
    report, _, _ = _assert_contract(_run(engine, {"AAA": broken}))
    assert [c.check for c in report.checks] == ["schema"], (
        "checks after schema should not run on a frame known to be malformed"
    )
