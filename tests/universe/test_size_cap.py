"""Universe size cap (`filters.max_universe_size`).

The cap is what keeps a real-data daily run finishing: everything
downstream of the universe scales with its size, and the Korean listed
universe is ~2,700 names before filters. Two properties matter and are
easy to break by accident:

* it keeps the **most liquid** names, not an arbitrary slice; and
* capped names remain in the snapshot marked excluded with a reason, so
  the universe file stays an honest record of what was considered.
"""
from __future__ import annotations

import pytest

from quant.universe.engine import UniverseEngine, UniverseMember


def _member(symbol: str, trading_value: float | None, included: bool = True) -> UniverseMember:
    return UniverseMember(
        symbol=symbol, name=symbol, exchange="KOSPI", asset_type="equity",
        price=10_000.0, avg_trading_value=trading_value, market_cap=1e12,
        listed_days=1000, included=included, exclusion_reasons=[] if included else ["preexisting"],
    )


def test_cap_keeps_the_most_liquid_names():
    members = [_member(f"S{i:03d}", trading_value=float(i)) for i in range(10)]

    UniverseEngine._apply_size_cap(members, max_size=3)

    kept = sorted(m.symbol for m in members if m.included)
    assert kept == ["S007", "S008", "S009"], "should keep the three highest trading values"


def test_capped_names_stay_in_the_snapshot_with_a_reason():
    members = [_member(f"S{i:03d}", trading_value=float(i)) for i in range(10)]

    UniverseEngine._apply_size_cap(members, max_size=3)

    assert len(members) == 10, "capped names must not be dropped from the snapshot"
    dropped = [m for m in members if not m.included]
    assert len(dropped) == 7
    for m in dropped:
        assert any("below_universe_size_cap" in r for r in m.exclusion_reasons)


def test_cap_does_not_resurrect_already_excluded_names():
    members = [_member("GOOD", 100.0), _member("BAD", 999.0, included=False)]

    UniverseEngine._apply_size_cap(members, max_size=1)

    by_symbol = {m.symbol: m for m in members}
    assert by_symbol["GOOD"].included is True
    assert by_symbol["BAD"].included is False, (
        "a name excluded by a real filter must stay excluded no matter how liquid"
    )
    assert by_symbol["BAD"].exclusion_reasons == ["preexisting"]


def test_missing_liquidity_sorts_last_rather_than_crashing():
    members = [_member("HAS_DATA", 50.0), _member("NO_DATA", None)]

    UniverseEngine._apply_size_cap(members, max_size=1)

    by_symbol = {m.symbol: m for m in members}
    assert by_symbol["HAS_DATA"].included is True
    assert by_symbol["NO_DATA"].included is False


@pytest.mark.parametrize("max_size", [0, None])
def test_cap_disabled_leaves_everything_untouched(max_size):
    members = [_member(f"S{i:03d}", trading_value=float(i)) for i in range(10)]

    UniverseEngine._apply_size_cap(members, max_size=max_size)

    assert all(m.included for m in members)


def test_universe_smaller_than_cap_is_untouched():
    members = [_member(f"S{i:03d}", trading_value=float(i)) for i in range(3)]

    UniverseEngine._apply_size_cap(members, max_size=100)

    assert all(m.included for m in members)
    assert all(m.exclusion_reasons == [] for m in members)


def test_configured_cap_is_actually_applied_by_build(monkeypatch):
    """End-to-end through `build()`: a config cap of 2 must bind."""
    from quant.data.synthetic_provider import SyntheticDataProvider

    provider = SyntheticDataProvider(market="korea", n_symbols=40, n_etfs=5,
                                     start="2015-01-01", end="2023-12-31", seed=3)
    engine = UniverseEngine("korea", provider)
    capped_cfg = dict(engine.cfg)
    capped_cfg["filters"] = dict(capped_cfg["filters"], max_universe_size=2)
    monkeypatch.setattr(engine, "cfg", capped_cfg)

    snap = engine.build(as_of="2022-06-01")

    assert len(snap.included_symbols()) <= 2
