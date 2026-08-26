import pandas as pd

from quant import config
from quant.quality.audit import AuditLog, VersionStore, compute_checksum, detect_historical_revision
from quant.quality.models import AuditRecord
from tests.quality.conftest import make_records

CFG = config.quality_config()


def test_checksum_is_stable_regardless_of_row_order():
    df = make_records([
        {"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"symbol": "B", "date": "2026-08-03", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 2000},
    ])
    shuffled = df.iloc[::-1].reset_index(drop=True)
    assert compute_checksum(df) == compute_checksum(shuffled)


def test_checksum_changes_when_a_value_changes():
    df1 = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    df2 = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 101, "volume": 1000}])
    assert compute_checksum(df1) != compute_checksum(df2)


def test_version_store_is_idempotent_for_unchanged_checksum(tmp_path):
    store = VersionStore(tmp_path / "versions.json")
    v1 = store.record("korea", "2026-08-26", "abc123")
    v2 = store.record("korea", "2026-08-26", "abc123")
    assert v1.version == v2.version == 1
    assert v1.tag == "korea_2026-08-26_v1"


def test_version_store_bumps_version_on_checksum_change(tmp_path):
    store = VersionStore(tmp_path / "versions.json")
    store.record("korea", "2026-08-26", "abc123")
    v2 = store.record("korea", "2026-08-26", "def456")
    assert v2.version == 2
    assert v2.tag == "korea_2026-08-26_v2"


def test_version_store_persists_across_instances(tmp_path):
    path = tmp_path / "versions.json"
    VersionStore(path).record("korea", "2026-08-26", "abc123")
    reloaded = VersionStore(path)
    v = reloaded.get("korea", "2026-08-26")
    assert v.version == 1
    assert v.checksum == "abc123"


def test_audit_log_appends_and_reads_back(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(AuditRecord(
        timestamp="2026-08-26T00:00:00Z", market="korea", symbol=None, source="primary",
        data_version="korea_2026-08-26_v1", checksum="abc123", check="schema", result="PASS",
    ))
    log.append(AuditRecord(
        timestamp="2026-08-26T00:00:01Z", market="korea", symbol=None, source="primary",
        data_version="korea_2026-08-26_v1", checksum="abc123", check="ohlc_integrity", result="PASS",
    ))
    records = log.read_all()
    assert len(records) == 2
    assert records[0]["check"] == "schema"


def test_historical_revision_detected_when_stored_value_changes():
    stored = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    fresh = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 105, "volume": 1000}])
    issues, n_revised = detect_historical_revision(stored, fresh, "korea", CFG)
    assert n_revised == 1
    assert any("HISTORICAL_DATA_REVISION" in i.message for i in issues)


def test_no_revision_when_values_are_unchanged():
    stored = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    fresh = make_records([{"symbol": "A", "date": "2026-08-03", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}])
    issues, n_revised = detect_historical_revision(stored, fresh, "korea", CFG)
    assert n_revised == 0
    assert issues == []
