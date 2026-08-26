import pytest

from quant import config
from quant.broker.kr_live import KoreaLiveBroker
from quant.broker.us_live import USLiveBroker


def test_live_trading_hard_locked_false():
    assert config.is_live_trading_enabled() is False


def test_korea_live_broker_cannot_be_instantiated():
    with pytest.raises(NotImplementedError):
        KoreaLiveBroker()


def test_us_live_broker_cannot_be_instantiated():
    with pytest.raises(NotImplementedError):
        USLiveBroker()


def test_hard_lock_survives_env_var_override(monkeypatch):
    # even if a user sets LIVE_TRADING=true in their environment, the
    # hardcoded source-level lock in config.py must keep this False
    monkeypatch.setenv("LIVE_TRADING", "true")
    assert config.is_live_trading_enabled() is False
