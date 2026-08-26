import pandas as pd
import pytest

from quant.research_db.db import ResearchDB
from quant.research_db.models import ExperimentRecord, dataset_version_tag, new_experiment_id


def _record(**overrides) -> ExperimentRecord:
    base = dict(
        experiment_id=new_experiment_id(),
        created_at=pd.Timestamp.now(),
        market="korea",
        strategy_id="ma_crossover",
        params={"fast_window": 20, "slow_window": 60},
        universe_description="KOSPI+KOSDAQ, 120 symbols",
        backtest_start="2015-01-01",
        backtest_end="2023-12-31",
        is_metrics={"sharpe": 0.9, "cagr": 0.10},
        oos_metrics={"sharpe": 0.7, "cagr": 0.08},
        aggregate_oos_metrics={"sharpe": 0.75, "cagr": 0.085},
        cost_config={"commission_rate": 0.00015},
        code_version="abc123",
        dataset_version=dataset_version_tag("korea", ["A", "B"], "2015-01-01", "2023-12-31"),
        composite_score=0.65,
        overfitting_risk="low",
    )
    base.update(overrides)
    return ExperimentRecord(**base)


@pytest.fixture
def db(tmp_path):
    return ResearchDB(path=tmp_path / "research.sqlite")


def test_save_and_get_experiment_roundtrip(db):
    record = _record()
    exp_id = db.save_experiment(record)
    fetched = db.get_experiment(exp_id)
    assert fetched is not None
    assert fetched.strategy_id == "ma_crossover"
    assert fetched.params == {"fast_window": 20, "slow_window": 60}
    assert fetched.is_metrics["sharpe"] == 0.9


def test_get_missing_experiment_returns_none(db):
    assert db.get_experiment("does_not_exist") is None


def test_query_experiments_filters_by_market_and_strategy(db):
    db.save_experiment(_record(market="korea", strategy_id="ma_crossover"))
    db.save_experiment(_record(market="us", strategy_id="rsi_reversal"))
    db.save_experiment(_record(market="korea", strategy_id="rsi_reversal"))

    korea_only = db.query_experiments(market="korea")
    assert len(korea_only) == 2
    assert set(korea_only["market"]) == {"korea"}

    ma_only = db.query_experiments(strategy_id="ma_crossover")
    assert len(ma_only) == 1


def test_latest_experiment_returns_most_recent(db):
    old = _record(created_at=pd.Timestamp("2020-01-01"), composite_score=0.1)
    new = _record(created_at=pd.Timestamp("2023-01-01"), composite_score=0.9)
    db.save_experiment(old)
    db.save_experiment(new)

    latest = db.latest_experiment("korea", "ma_crossover")
    assert latest.composite_score == pytest.approx(0.9)


def test_delete_experiment(db):
    record = _record()
    exp_id = db.save_experiment(record)
    db.delete_experiment(exp_id)
    assert db.get_experiment(exp_id) is None


def test_count(db):
    assert db.count() == 0
    db.save_experiment(_record())
    assert db.count() == 1


def test_dataset_version_tag_is_deterministic():
    tag1 = dataset_version_tag("korea", ["B", "A"], "2015-01-01", "2023-12-31")
    tag2 = dataset_version_tag("korea", ["A", "B"], "2015-01-01", "2023-12-31")
    assert tag1 == tag2  # order-independent

    tag3 = dataset_version_tag("korea", ["A", "B", "C"], "2015-01-01", "2023-12-31")
    assert tag3 != tag1
