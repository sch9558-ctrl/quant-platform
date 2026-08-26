import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard"))

import data_access  # noqa: E402


def test_run_scan_demo_mode_returns_candidates():
    scan = data_access.run_scan("korea", "2022-06-01", demo=True, top_n=5)
    assert scan.market == "korea"
    assert len(scan.top_candidates) <= 5


def test_candidates_to_frame_shape():
    scan = data_access.run_scan("korea", "2022-06-01", demo=True, top_n=5)
    df = data_access.candidates_to_frame(scan)
    assert "symbol" in df.columns
    assert "composite_score" in df.columns


def test_enabled_strategy_ids_nonempty():
    ids = data_access.enabled_strategy_ids()
    assert len(ids) >= 10


def test_load_experiments_empty_db_returns_empty_frame(tmp_path, monkeypatch):
    from quant.research_db.db import ResearchDB

    monkeypatch.setattr(data_access, "ResearchDB", lambda: ResearchDB(path=tmp_path / "research.sqlite"))
    df = data_access.load_experiments()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_run_quick_backtest_demo_mode():
    result = data_access.run_quick_backtest("ma_crossover", "korea", demo=True, start="2018-01-01", end="2021-12-31")
    assert not result.equity_curve.empty


def test_get_paper_broker_returns_market_specific_broker(tmp_path, monkeypatch):
    from quant import config as quant_config

    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)
    kr = data_access.get_paper_broker("korea")
    us = data_access.get_paper_broker("us")
    assert kr.market == "korea"
    assert us.market == "us"
    assert kr.get_cash() > 0
    assert us.get_cash() > 0


def test_run_paper_rebalance_demo_mode(tmp_path, monkeypatch):
    from quant import config as quant_config

    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)
    broker, scan, results = data_access.run_paper_rebalance("korea", demo=True, top_n=5)
    assert scan.market == "korea"
    if scan.top_candidates:
        assert len(results) == len(scan.top_candidates)
        assert not broker.get_equity_curve().empty
    else:
        assert results == []
