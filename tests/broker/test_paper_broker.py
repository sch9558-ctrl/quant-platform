import pytest
import pandas as pd

from quant.broker.base import Fill, OrderRejection
from quant.broker.kr_paper import KoreaPaperBroker
from quant.research_db.db import ResearchDB


@pytest.fixture
def broker(tmp_path):
    return KoreaPaperBroker(initial_capital=10_000_000, state_path=tmp_path / "paper_korea.json")


def test_initial_state(broker):
    assert broker.get_cash() == 10_000_000
    assert broker.get_positions() == {}
    assert broker.get_account_value() == 10_000_000


def test_buy_order_reduces_cash_and_creates_position(broker):
    fill = broker.submit_order("AAA", "buy", quantity=100, price=1000, session=pd.Timestamp("2026-01-05"))
    assert isinstance(fill, Fill)
    assert fill.side == "buy"
    positions = broker.get_positions()
    assert "AAA" in positions
    assert positions["AAA"].quantity == pytest.approx(100)
    assert broker.get_cash() < 10_000_000 - 100 * 1000 + 1  # notional + cost deducted


def test_buy_exceeding_position_cap_gets_reduced(broker):
    # default risk config caps a single position at 10% of NAV; requesting
    # a huge quantity should get scaled down, not fully rejected
    fill = broker.submit_order("AAA", "buy", quantity=5000, price=1000, session=pd.Timestamp("2026-01-05"))  # 5,000,000 notional = 50% of NAV
    assert isinstance(fill, Fill)
    notional = fill.quantity * fill.price
    assert notional <= 10_000_000 * 0.10 * 1.01


def test_sell_reduces_position():
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        broker = KoreaPaperBroker(initial_capital=10_000_000, state_path=Path(d) / "state.json")
        broker.submit_order("AAA", "buy", quantity=50, price=1000, session=pd.Timestamp("2026-01-05"))
        fill = broker.submit_order("AAA", "sell", quantity=20, price=1100, session=pd.Timestamp("2026-01-06"))
        assert fill.side == "sell"
        assert broker.get_positions()["AAA"].quantity == pytest.approx(30)


def test_sell_full_position_removes_it(broker):
    broker.submit_order("AAA", "buy", quantity=50, price=1000, session=pd.Timestamp("2026-01-05"))
    broker.submit_order("AAA", "sell", quantity=50, price=1000, session=pd.Timestamp("2026-01-06"))
    assert "AAA" not in broker.get_positions()


def test_invalid_order_rejected(broker):
    result = broker.submit_order("AAA", "buy", quantity=-5, price=1000, session=pd.Timestamp("2026-01-05"))
    assert isinstance(result, OrderRejection)


def test_state_persists_across_broker_instances(tmp_path):
    path = tmp_path / "paper_korea.json"
    b1 = KoreaPaperBroker(initial_capital=5_000_000, state_path=path)
    b1.submit_order("AAA", "buy", quantity=10, price=1000, session=pd.Timestamp("2026-01-05"))

    b2 = KoreaPaperBroker(initial_capital=5_000_000, state_path=path)
    assert "AAA" in b2.get_positions()
    assert b2.get_cash() == pytest.approx(b1.get_cash())


def test_rebalance_to_target_weights(broker):
    results = broker.rebalance_to_target_weights({"AAA": 0.05, "BBB": 0.03}, {"AAA": 1000, "BBB": 2000}, session=pd.Timestamp("2026-01-05"))
    assert len(results) == 2
    assert all(isinstance(r, Fill) for r in results)
    positions = broker.get_positions()
    assert "AAA" in positions and "BBB" in positions


def test_record_daily_equity_and_curve(broker):
    broker.record_daily_equity({}, as_of=__import__("pandas").Timestamp("2023-01-01"))
    broker.submit_order("AAA", "buy", quantity=10, price=1000, session=pd.Timestamp("2023-01-01"))
    broker.record_daily_equity({"AAA": 1000}, as_of=__import__("pandas").Timestamp("2023-01-02"))
    curve = broker.get_equity_curve()
    assert len(curve) == 2


def test_consecutive_losses_tracked(broker):
    import pandas as pd
    broker.record_daily_equity({}, as_of=pd.Timestamp("2023-01-01"))
    broker.submit_order("AAA", "buy", quantity=100, price=1000, session=pd.Timestamp("2023-01-01"))
    broker.record_daily_equity({"AAA": 900}, as_of=pd.Timestamp("2023-01-02"))  # price dropped
    assert broker.consecutive_losses >= 1
    broker.record_daily_equity({"AAA": 1200}, as_of=pd.Timestamp("2023-01-03"))  # price recovered
    assert broker.consecutive_losses == 0


def test_reset_clears_state(broker):
    broker.submit_order("AAA", "buy", quantity=10, price=1000, session=pd.Timestamp("2023-01-01"))
    broker.reset()
    assert broker.get_positions() == {}
    assert broker.get_cash() == broker.initial_capital



def test_research_db_projection_survives_restart_and_is_as_of_safe(tmp_path):
    import pandas as pd

    state_path = tmp_path / "paper_korea.json"
    research_db = ResearchDB(path=tmp_path / "research.sqlite")

    first = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=state_path,
        research_db=research_db,
    )
    fill = first.submit_order(
        "AAA", "buy", quantity=100, price=1000,
        session=pd.Timestamp("2026-01-05"),
    )
    assert isinstance(fill, Fill)
    first.record_daily_equity(
        {"AAA": 1010},
        as_of=pd.Timestamp("2026-01-05"),
    )

    january = research_db.latest_paper_state_as_of(
        market="korea",
        as_of="2026-01-05",
    )
    assert january is not None
    assert january["positions"]["AAA"]["quantity"] == pytest.approx(100)
    assert january["positions"]["AAA"]["entry_session"] == "2026-01-05"
    january_nav = january["nav"]
    january_cash = january["cash"]

    restarted = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=state_path,
        research_db=research_db,
    )
    assert restarted.get_cash() == pytest.approx(first.get_cash())
    assert restarted.get_positions()["AAA"].entry_session == "2026-01-05"

    sell = restarted.submit_order(
        "AAA", "sell", quantity=50, price=1100,
        session=pd.Timestamp("2026-02-02"),
    )
    assert isinstance(sell, Fill)
    restarted.record_daily_equity(
        {"AAA": 1100},
        as_of=pd.Timestamp("2026-02-02"),
    )

    january_after_future_fill = research_db.latest_paper_state_as_of(
        market="korea",
        as_of="2026-01-05",
    )
    assert january_after_future_fill is not None
    assert january_after_future_fill["nav"] == pytest.approx(january_nav)
    assert january_after_future_fill["cash"] == pytest.approx(january_cash)
    assert january_after_future_fill["positions"]["AAA"]["quantity"] == pytest.approx(100)

    february = research_db.latest_paper_state_as_of(
        market="korea",
        as_of="2026-02-02",
    )
    assert february is not None
    assert february["positions"]["AAA"]["quantity"] == pytest.approx(50)

    old_fills = research_db.paper_fills_as_of(
        market="korea",
        as_of="2026-01-31",
    )
    assert list(old_fills["side"]) == ["buy"]
    all_fills = research_db.paper_fills_as_of(
        market="korea",
        as_of="2026-02-02",
    )
    assert list(all_fills["side"]) == ["buy", "sell"]


def test_repeated_identical_mark_keeps_persistent_state_values_stable(tmp_path):
    import pandas as pd

    research_db = ResearchDB(path=tmp_path / "research.sqlite")
    broker = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=tmp_path / "paper_korea.json",
        research_db=research_db,
    )
    broker.submit_order(
        "AAA", "buy", quantity=50, price=1000,
        session=pd.Timestamp("2026-01-05"),
    )
    broker.record_daily_equity({"AAA": 1050}, as_of=pd.Timestamp("2026-01-06"))
    first = research_db.latest_paper_state_as_of(market="korea", as_of="2026-01-06")

    broker.record_daily_equity({"AAA": 1050}, as_of=pd.Timestamp("2026-01-06"))
    second = research_db.latest_paper_state_as_of(market="korea", as_of="2026-01-06")

    assert first is not None and second is not None
    assert second["cash"] == pytest.approx(first["cash"])
    assert second["nav"] == pytest.approx(first["nav"])
    assert second["positions"] == first["positions"]


def test_persistent_nav_history_excludes_future_sessions(tmp_path):
    import pandas as pd

    research_db = ResearchDB(path=tmp_path / "research.sqlite")
    broker = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=tmp_path / "paper_korea.json",
        research_db=research_db,
    )
    broker.record_daily_equity({}, as_of=pd.Timestamp("2026-01-05"))
    broker.record_daily_equity({}, as_of=pd.Timestamp("2026-02-02"))

    january = research_db.paper_nav_history(
        market="korea",
        as_of="2026-01-31",
    )
    assert list(january.index.strftime("%Y-%m-%d")) == ["2026-01-05"]



def test_persistent_nav_volatility_target_reduces_only_with_enough_history():
    import pandas as pd
    from run_paper import apply_persistent_nav_volatility_target

    class FakeDB:
        def __init__(self, nav):
            self.nav = nav

        def paper_nav_history(self, *, market, as_of):
            return self.nav.loc[:pd.Timestamp(as_of)]

    class FakeBroker:
        market = "korea"

        def __init__(self, nav):
            self.research_db = FakeDB(nav)

    index = pd.bdate_range("2026-01-02", periods=30)
    # Deliberately volatile but positive NAV path: enough evidence should
    # cause the 12% target-vol overlay to de-risk, never lever up.
    nav = pd.Series(
        [100.0 * (1.04 if i % 2 == 0 else 0.96) ** (i + 1) for i in range(30)],
        index=index,
    )
    weights = {"AAA": 0.08, "BBB": 0.07}
    adjusted, meta = apply_persistent_nav_volatility_target(
        weights,
        FakeBroker(nav),
        as_of=str(index[-1].date()),
    )
    assert meta["applied"] is True
    assert 0.0 <= meta["risky_weight"] < 1.0
    assert adjusted["AAA"] < weights["AAA"]
    assert adjusted["BBB"] < weights["BBB"]

    short_nav = nav.iloc[:10]
    unchanged, short_meta = apply_persistent_nav_volatility_target(
        weights,
        FakeBroker(short_nav),
        as_of=str(short_nav.index[-1].date()),
    )
    assert short_meta["applied"] is False
    assert short_meta["reason"] == "INSUFFICIENT_PERSISTENT_NAV_HISTORY"
    assert unchanged == weights



def test_backdated_paper_mutation_is_rejected(tmp_path):
    import pandas as pd

    broker = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=tmp_path / "paper_korea.json",
        research_db=ResearchDB(path=tmp_path / "research.sqlite"),
    )
    broker.record_daily_equity({}, as_of=pd.Timestamp("2026-02-02"))

    with pytest.raises(ValueError, match="cannot mutate past session"):
        broker.submit_order(
            "AAA", "buy", quantity=10, price=1000,
            session=pd.Timestamp("2026-01-05"),
        )


def test_persistent_paper_mutations_require_explicit_session(tmp_path):
    broker = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=tmp_path / "paper_korea.json",
    )
    with pytest.raises(ValueError, match="explicit session"):
        broker.submit_order("AAA", "buy", quantity=10, price=1000)
    with pytest.raises(ValueError, match="explicit session"):
        broker.rebalance_to_target_weights({"AAA": 0.05}, {"AAA": 1000})
    with pytest.raises(ValueError, match="explicit as_of session"):
        broker.record_daily_equity({})


@pytest.mark.parametrize("fake_today", ["2026-01-15", "2026-06-30", "2027-03-02"])
def test_explicit_paper_session_is_independent_of_fake_today(tmp_path, monkeypatch, fake_today):
    import quant.utils.calendar as market_calendar

    monkeypatch.setattr(market_calendar, "default_as_of", lambda market: fake_today)
    broker = KoreaPaperBroker(
        initial_capital=10_000_000,
        state_path=tmp_path / f"paper_{fake_today}.json",
    )
    fill = broker.submit_order(
        "AAA", "buy", quantity=10, price=1000,
        session=pd.Timestamp("2026-01-05"),
        filled_at=pd.Timestamp("2026-01-05T15:30:00+09:00"),
    )
    assert isinstance(fill, Fill)
    assert fill.session == pd.Timestamp("2026-01-05")
    assert fill.filled_at == pd.Timestamp("2026-01-05T15:30:00+09:00")
    assert broker.get_positions()["AAA"].entry_session == "2026-01-05"
