import pytest

from quant.broker.base import Fill, OrderRejection
from quant.broker.kr_paper import KoreaPaperBroker


@pytest.fixture
def broker(tmp_path):
    return KoreaPaperBroker(initial_capital=10_000_000, state_path=tmp_path / "paper_korea.json")


def test_initial_state(broker):
    assert broker.get_cash() == 10_000_000
    assert broker.get_positions() == {}
    assert broker.get_account_value() == 10_000_000


def test_buy_order_reduces_cash_and_creates_position(broker):
    fill = broker.submit_order("AAA", "buy", quantity=100, price=1000)
    assert isinstance(fill, Fill)
    assert fill.side == "buy"
    positions = broker.get_positions()
    assert "AAA" in positions
    assert positions["AAA"].quantity == pytest.approx(100)
    assert broker.get_cash() < 10_000_000 - 100 * 1000 + 1  # notional + cost deducted


def test_buy_exceeding_position_cap_gets_reduced(broker):
    # default risk config caps a single position at 10% of NAV; requesting
    # a huge quantity should get scaled down, not fully rejected
    fill = broker.submit_order("AAA", "buy", quantity=5000, price=1000)  # 5,000,000 notional = 50% of NAV
    assert isinstance(fill, Fill)
    notional = fill.quantity * fill.price
    assert notional <= 10_000_000 * 0.10 * 1.01


def test_sell_reduces_position():
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        broker = KoreaPaperBroker(initial_capital=10_000_000, state_path=Path(d) / "state.json")
        broker.submit_order("AAA", "buy", quantity=50, price=1000)
        fill = broker.submit_order("AAA", "sell", quantity=20, price=1100)
        assert fill.side == "sell"
        assert broker.get_positions()["AAA"].quantity == pytest.approx(30)


def test_sell_full_position_removes_it(broker):
    broker.submit_order("AAA", "buy", quantity=50, price=1000)
    broker.submit_order("AAA", "sell", quantity=50, price=1000)
    assert "AAA" not in broker.get_positions()


def test_invalid_order_rejected(broker):
    result = broker.submit_order("AAA", "buy", quantity=-5, price=1000)
    assert isinstance(result, OrderRejection)


def test_state_persists_across_broker_instances(tmp_path):
    path = tmp_path / "paper_korea.json"
    b1 = KoreaPaperBroker(initial_capital=5_000_000, state_path=path)
    b1.submit_order("AAA", "buy", quantity=10, price=1000)

    b2 = KoreaPaperBroker(initial_capital=5_000_000, state_path=path)
    assert "AAA" in b2.get_positions()
    assert b2.get_cash() == pytest.approx(b1.get_cash())


def test_rebalance_to_target_weights(broker):
    results = broker.rebalance_to_target_weights({"AAA": 0.05, "BBB": 0.03}, {"AAA": 1000, "BBB": 2000})
    assert len(results) == 2
    assert all(isinstance(r, Fill) for r in results)
    positions = broker.get_positions()
    assert "AAA" in positions and "BBB" in positions


def test_record_daily_equity_and_curve(broker):
    broker.record_daily_equity({}, as_of=__import__("pandas").Timestamp("2023-01-01"))
    broker.submit_order("AAA", "buy", quantity=10, price=1000)
    broker.record_daily_equity({"AAA": 1000}, as_of=__import__("pandas").Timestamp("2023-01-02"))
    curve = broker.get_equity_curve()
    assert len(curve) == 2


def test_consecutive_losses_tracked(broker):
    import pandas as pd
    broker.record_daily_equity({}, as_of=pd.Timestamp("2023-01-01"))
    broker.submit_order("AAA", "buy", quantity=100, price=1000)
    broker.record_daily_equity({"AAA": 900}, as_of=pd.Timestamp("2023-01-02"))  # price dropped
    assert broker.consecutive_losses >= 1
    broker.record_daily_equity({"AAA": 1200}, as_of=pd.Timestamp("2023-01-03"))  # price recovered
    assert broker.consecutive_losses == 0


def test_reset_clears_state(broker):
    broker.submit_order("AAA", "buy", quantity=10, price=1000)
    broker.reset()
    assert broker.get_positions() == {}
    assert broker.get_cash() == broker.initial_capital
