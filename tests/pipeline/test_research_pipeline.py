"""Tests for the Research Pipeline orchestrator (spec section 35).

Keeps the strategy universe small (monkeypatched `enabled_strategy_ids`)
and the backtest lookback short (falls back to a single Fixed Split fold
instead of multi-fold Walk-Forward, since 3 years < validation.yaml's
`min_total_years: 6`) so this stays a fast unit test rather than a slow
full research run -- `run_research.py` (manually exercised, not in the
routine test suite) is what actually evaluates every strategy across the
full multi-fold history.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.pipeline import research_pipeline
from quant.research_db.db import ResearchDB
from quant.strategy import registry


@pytest.fixture(autouse=True)
def _small_strategy_universe(monkeypatch):
    # Only evaluate two fast, config-default-param strategies instead of
    # all twelve, so these tests run in seconds, not minutes.
    monkeypatch.setattr(registry, "enabled_strategy_ids", lambda: ["ma_crossover", "rsi_reversal"])


@pytest.fixture
def db(tmp_path):
    return ResearchDB(path=tmp_path / "research.sqlite")


def test_build_backtest_inputs_returns_aligned_ohlcv_and_features():
    from quant.data.factory import get_provider

    provider = get_provider("korea", demo=True)
    equity_symbols = [s.symbol for s in provider.list_symbols() if s.asset_type == "equity"][:5]

    ohlcv_map, feature_map, benchmark_close = research_pipeline._build_backtest_inputs(
        "korea", provider, equity_symbols, "2022-06-01", 3,
    )
    assert set(ohlcv_map) == set(feature_map)
    assert len(ohlcv_map) > 0
    assert isinstance(benchmark_close, pd.Series)
    assert not benchmark_close.empty
    for sym, feat_df in feature_map.items():
        assert "momentum_rank" in feat_df.columns
        assert feat_df.index.equals(ohlcv_map[sym].index)


def test_run_market_research_end_to_end(db):
    result = research_pipeline.run_market_research(
        "korea", demo=True, as_of="2022-06-01", top_n=5,
        use_param_search=False, lookback_years=3, db=db,
    )

    assert result.market == "korea"
    assert set(result.walk_forward_results.keys()) == {"ma_crossover", "rsi_reversal"}
    assert not result.ranking_df.empty
    assert len(result.experiment_ids) == 2
    assert set(result.new_strategy_ids) == {"ma_crossover", "rsi_reversal"}
    assert result.updated_strategy_ids == []
    assert isinstance(result.portfolio_allocation.weights, pd.Series)
    assert len(result.risk_checks) == len(result.portfolio_allocation.weights)


def test_run_market_research_marks_repeat_strategies_as_updated(db):
    research_pipeline.run_market_research(
        "korea", demo=True, as_of="2022-06-01", top_n=5,
        use_param_search=False, lookback_years=3, db=db,
    )
    second = research_pipeline.run_market_research(
        "korea", demo=True, as_of="2022-06-02", top_n=5,
        use_param_search=False, lookback_years=3, db=db,
    )
    assert second.new_strategy_ids == []
    assert set(second.updated_strategy_ids) == {"ma_crossover", "rsi_reversal"}


def test_run_full_pipeline_writes_report(tmp_path, monkeypatch):
    from quant import config as quant_config

    original_settings = quant_config.settings()
    patched = {**original_settings, "paths": {**original_settings["paths"], "reports_dir": str(tmp_path)}}
    monkeypatch.setattr(quant_config, "settings", lambda: patched)
    monkeypatch.setattr(research_pipeline.config, "resolve_path", lambda rel: tmp_path)
    monkeypatch.setattr(research_pipeline, "ResearchDB", lambda: ResearchDB(path=tmp_path / "research.sqlite"))

    result = research_pipeline.run_full_pipeline(
        demo=True, as_of="2022-06-01", top_n=5, use_param_search=False, markets=("korea",),
    )

    assert "korea" in result.markets
    assert "# Daily Research Report" in result.report_text
    assert result.report_path
    from pathlib import Path
    assert Path(result.report_path).exists()
