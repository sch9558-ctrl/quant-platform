from quant.quality.pipeline_gate import validate_market


def test_validate_market_demo_mode_passes_and_produces_canonical_data(tmp_path, monkeypatch):
    from quant import config as quant_config
    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    result = validate_market("korea", demo=True, as_of="2022-06-01", lookback_days=100)
    assert result.report.overall_status == "PASS"
    assert result.report.mandatory_validation_pass_rate == 100.0
    assert len(result.canonical_ohlcv_map) > 0
    assert result.universe_snapshot.market == "korea"
    assert result.report.data_version is not None


def test_validate_market_is_idempotent_across_runs(tmp_path, monkeypatch):
    from quant import config as quant_config
    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    r1 = validate_market("korea", demo=True, as_of="2022-06-01", lookback_days=100)
    r2 = validate_market("korea", demo=True, as_of="2022-06-01", lookback_days=100)
    assert r1.report.data_version == r2.report.data_version


def test_validate_market_us_also_passes(tmp_path, monkeypatch):
    from quant import config as quant_config
    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    result = validate_market("us", demo=True, as_of="2022-06-01", lookback_days=100)
    assert result.report.overall_status == "PASS"


def test_without_secondary_cross_source_is_skipped_not_failed(tmp_path, monkeypatch):
    from quant import config as quant_config
    monkeypatch.setattr(quant_config, "resolve_path", lambda rel: tmp_path)

    result = validate_market("korea", demo=True, as_of="2022-06-01", lookback_days=100, use_secondary=False)
    assert result.report.overall_status == "PASS"
    cross_source_check = next(c for c in result.report.checks if c.check == "cross_source")
    assert not cross_source_check.mandatory
    assert cross_source_check.details["secondary_available"] is False
