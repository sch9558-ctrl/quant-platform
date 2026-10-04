import pandas as pd
import pytest

from quant.research_db.db import ResearchDB
from quant.research_db.models import (
    ExperimentRecord,
    PointInTimeObservation,
    dataset_version_tag,
    new_experiment_id,
    new_observation_id,
)


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


def _observation(**overrides) -> PointInTimeObservation:
    base = dict(
        observation_id=new_observation_id(),
        observation_type="analyst_consensus",
        source="fixture",
        market="us",
        symbol="AAPL",
        published_at=pd.Timestamp("2026-01-10T09:00:00Z"),
        collected_at=pd.Timestamp("2026-01-10T09:05:00Z"),
        effective_at=pd.Timestamp("2026-03-31T00:00:00Z"),
        payload={"target": 250.0},
        provenance={"source_id": "fixture-1"},
    )
    base.update(overrides)
    return PointInTimeObservation(**base)


def test_point_in_time_observation_roundtrip(db):
    record = _observation()
    obs_id = db.save_observation(record)
    frame = db.query_observations_as_of(
        observation_type="analyst_consensus",
        market="us",
        symbol="AAPL",
        as_of="2026-01-10T10:00:00Z",
    )
    assert len(frame) == 1
    assert frame.loc[0, "observation_id"] == obs_id
    latest = db.latest_observation_as_of(
        observation_type="analyst_consensus",
        market="us",
        symbol="AAPL",
        as_of="2026-01-10T10:00:00Z",
    )
    assert latest is not None
    assert latest.payload == {"target": 250.0}
    assert latest.provenance == {"source_id": "fixture-1"}


def test_point_in_time_query_excludes_future_publications(db):
    db.save_observation(_observation(
        published_at=pd.Timestamp("2026-01-10T09:00:00Z"),
        payload={"target": 240.0},
    ))
    db.save_observation(_observation(
        published_at=pd.Timestamp("2026-01-11T09:00:00Z"),
        collected_at=pd.Timestamp("2026-01-11T09:05:00Z"),
        payload={"target": 280.0},
    ))
    latest = db.latest_observation_as_of(
        observation_type="analyst_consensus",
        market="us",
        symbol="AAPL",
        as_of="2026-01-10T23:59:59Z",
    )
    assert latest is not None
    assert latest.payload["target"] == 240.0


def test_point_in_time_store_preserves_revisions_instead_of_overwriting(db):
    first = _observation(payload={"target": 240.0})
    second = _observation(
        published_at=pd.Timestamp("2026-01-10T09:00:00Z"),
        collected_at=pd.Timestamp("2026-01-10T11:00:00Z"),
        payload={"target": 245.0},
    )
    db.save_observation(first)
    db.save_observation(second)
    frame = db.query_observations_as_of(
        observation_type="analyst_consensus",
        market="us",
        symbol="AAPL",
        as_of="2026-01-10T23:59:59Z",
    )
    assert len(frame) == 2
    latest = db.latest_observation_as_of(
        observation_type="analyst_consensus",
        market="us",
        symbol="AAPL",
        as_of="2026-01-10T23:59:59Z",
    )
    assert latest is not None
    assert latest.payload["target"] == 245.0
