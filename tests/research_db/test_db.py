import pandas as pd
import pytest

from quant.research_db.db import DuplicateObservationError, ResearchDB
from quant.research_db.models import (
    ExperimentRecord,
    PointInTimeObservation,
    dataset_version_tag,
    new_experiment_id,
    observation_id_for,
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
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        published_at=pd.Timestamp("2026-01-10T09:00:00+09:00"),
        collected_at=pd.Timestamp("2026-01-10T09:05:00+09:00"),
        effective_at=None,
        payload={"target": 80_000.0},
        provenance={"source_id": "fixture-1"},
    )
    base.update(overrides)
    return PointInTimeObservation(**base)


def test_point_in_time_observation_roundtrip_uses_deterministic_identity(db):
    record = _observation()
    obs_id = db.save_observation(record)
    assert obs_id == observation_id_for(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        published_at=record.published_at,
    )
    latest = db.latest_observation_as_of(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        as_of="2026-03-01T23:59:59+09:00",
    )
    assert latest is not None
    assert latest.observation_id == obs_id
    assert latest.payload["target"] == 80_000.0


def test_point_in_time_revision_preserves_both_public_releases(db):
    january = _observation(
        published_at=pd.Timestamp("2026-01-10T09:00:00+09:00"),
        collected_at=pd.Timestamp("2026-01-10T09:05:00+09:00"),
        payload={"target": 80_000.0},
    )
    june = _observation(
        published_at=pd.Timestamp("2026-06-15T09:00:00+09:00"),
        collected_at=pd.Timestamp("2026-06-15T09:03:00+09:00"),
        payload={"target": 95_000.0},
        provenance={"source_id": "fixture-2", "revision_of": january.canonical_id()},
    )
    jan_id=db.save_observation(january)
    june_id=db.save_observation(june)
    assert jan_id != june_id

    march=db.latest_observation_as_of(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        as_of="2026-03-01T23:59:59+09:00",
    )
    july=db.latest_observation_as_of(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        as_of="2026-07-01T23:59:59+09:00",
    )
    assert march is not None and march.payload["target"] == 80_000.0
    assert july is not None and july.payload["target"] == 95_000.0

    frame=db.query_observations_as_of(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        as_of="2026-07-01T23:59:59+09:00",
    )
    assert len(frame) == 2
    assert set(frame["observation_id"]) == {jan_id,june_id}


def test_same_publication_duplicate_raises_domain_error(db):
    original=_observation()
    db.save_observation(original)
    duplicate=_observation(
        collected_at=pd.Timestamp("2026-01-10T10:00:00+09:00"),
        payload={"target": 80_500.0},
    )
    with pytest.raises(DuplicateObservationError,match="same logical observation"):
        db.save_observation(duplicate)


def test_point_in_time_query_excludes_future_publications(db):
    db.save_observation(_observation(
        published_at=pd.Timestamp("2026-01-10T09:00:00+09:00"),
        payload={"target": 80_000.0},
    ))
    db.save_observation(_observation(
        published_at=pd.Timestamp("2026-06-15T09:00:00+09:00"),
        collected_at=pd.Timestamp("2026-06-15T09:05:00+09:00"),
        payload={"target": 95_000.0},
    ))
    latest = db.latest_observation_as_of(
        observation_type="analyst_consensus",
        source="fixture_bank",
        market="korea",
        symbol="005930",
        as_of="2026-03-01T23:59:59+09:00",
    )
    assert latest is not None
    assert latest.payload["target"] == 80_000.0


def test_quality_quarantine_history_detects_consecutive_sessions(db):
    for session, symbols in [
        ("2026-10-01", ["AAA"]),
        ("2026-10-02", ["AAA", "BBB"]),
        ("2026-10-05", ["AAA"]),
    ]:
        db.save_quality_quarantine_snapshot(
            market="us",
            session=session,
            quarantined_symbols=symbols,
            resolution="PASS_AFTER_WHOLE_SYMBOL_QUARANTINE",
            raw_passed=False,
            validation_pass=True,
            quarantine_fraction=len(symbols) / 400,
        )
    state = db.quality_quarantine_streaks(
        market="us", as_of="2026-10-05", alert_sessions=3,
    )
    assert state["streaks"]["AAA"] == 3
    assert state["streaks"].get("BBB") is None
    assert state["alert_symbols"] == ["AAA"]


def test_quality_quarantine_failed_market_breaks_streak(db):
    db.save_quality_quarantine_snapshot(
        market="us", session="2026-10-01", quarantined_symbols=["AAA"],
        resolution="PASS_AFTER_WHOLE_SYMBOL_QUARANTINE", raw_passed=False,
        validation_pass=True, quarantine_fraction=0.0025,
    )
    db.save_quality_quarantine_snapshot(
        market="us", session="2026-10-02", quarantined_symbols=[],
        resolution="MARKET_FAIL_CLOSED", raw_passed=False,
        validation_pass=False, quarantine_fraction=0.3,
    )
    state = db.quality_quarantine_streaks(
        market="us", as_of="2026-10-02", alert_sessions=3,
    )
    assert state["streaks"] == {}
    assert state["alert_symbols"] == []


def test_quality_quarantine_same_session_same_verdict_is_idempotent(db):
    kwargs = dict(
        market="us", session="2026-10-01", quarantined_symbols=["AAA"],
        resolution="PASS_AFTER_WHOLE_SYMBOL_QUARANTINE", raw_passed=False,
        validation_pass=True, quarantine_fraction=0.0025,
    )
    first = db.save_quality_quarantine_snapshot(**kwargs)
    second = db.save_quality_quarantine_snapshot(**kwargs)
    assert first == second
    frame = db.query_observations_as_of(
        observation_type="quality_quarantine_snapshot",
        source="data_quality_engine",
        market="us", symbol=None, as_of="2026-10-01",
    )
    assert len(frame) == 1



def test_paper_cycle_summary_is_idempotent_and_queryable(db):
    kwargs = dict(
        market="us", session="2026-10-06", selected_symbols=["AAA", "BBB"],
        fills=2, rejections=0, nav=99_990.0, cash=60_000.0, positions=2,
    )
    first = db.save_paper_cycle_summary(**kwargs)
    second = db.save_paper_cycle_summary(**kwargs)
    assert first == second
    summary = db.latest_paper_cycle_summary(market="us", as_of="2026-10-06")
    assert summary["session"] == "2026-10-06"
    assert summary["selected_count"] == 2
    assert summary["fills"] == 2


def test_paper_cycle_summary_changed_same_session_is_rejected(db):
    db.save_paper_cycle_summary(
        market="us", session="2026-10-06", selected_symbols=["AAA"],
        fills=1, rejections=0, nav=99_995.0, cash=90_000.0, positions=1,
    )
    with pytest.raises(DuplicateObservationError):
        db.save_paper_cycle_summary(
            market="us", session="2026-10-06", selected_symbols=["AAA", "BBB"],
            fills=2, rejections=0, nav=99_990.0, cash=80_000.0, positions=2,
        )



def test_quality_quarantine_frequency_detects_intermittent_symbol(db):
    schedule = [
        ("2026-10-01", ["AAA"]),
        ("2026-10-02", ["AAA"]),
        ("2026-10-05", []),
        ("2026-10-06", ["AAA"]),
        ("2026-10-07", ["AAA"]),
        ("2026-10-08", []),
    ]
    for session, symbols in schedule:
        db.save_quality_quarantine_snapshot(
            market="us", session=session, quarantined_symbols=symbols,
            resolution=("PASS_AFTER_WHOLE_SYMBOL_QUARANTINE" if symbols else None),
            raw_passed=(False if symbols else True), validation_pass=True,
            quarantine_fraction=len(symbols) / 400,
        )
    freq = db.quality_quarantine_frequency(
        market="us", as_of="2026-10-08", window_sessions=20,
    )
    assert freq["observed_validated_sessions"] == 6
    assert freq["counts"]["AAA"] == 4
    assert freq["rates"]["AAA"] == pytest.approx(4 / 6)


def test_quality_quarantine_frequency_excludes_failed_market_sessions(db):
    db.save_quality_quarantine_snapshot(
        market="us", session="2026-10-01", quarantined_symbols=["AAA"],
        resolution="PASS_AFTER_WHOLE_SYMBOL_QUARANTINE", raw_passed=False,
        validation_pass=True, quarantine_fraction=0.0025,
    )
    db.save_quality_quarantine_snapshot(
        market="us", session="2026-10-02", quarantined_symbols=["AAA"],
        resolution="MARKET_FAIL_CLOSED", raw_passed=False,
        validation_pass=False, quarantine_fraction=0.3,
    )
    freq = db.quality_quarantine_frequency(
        market="us", as_of="2026-10-02", window_sessions=20,
    )
    assert freq["observed_validated_sessions"] == 1
    assert freq["counts"]["AAA"] == 1
