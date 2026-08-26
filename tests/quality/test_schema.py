from quant import config
from quant.quality.schema import validate_schema


def test_clean_records_pass_schema(clean_records):
    result = validate_schema(clean_records, "korea", config.quality_config()["schema"])
    assert result.passed
    assert result.mandatory


def test_missing_required_column_fails():
    import pandas as pd
    df = pd.DataFrame({"symbol": ["A"], "date": [pd.Timestamp("2026-08-03")], "open": [100.0]})
    result = validate_schema(df, "korea", config.quality_config()["schema"])
    assert not result.passed
    assert any("Missing required column" in i.message for i in result.issues)


def test_non_numeric_price_column_fails(clean_records):
    df = clean_records.copy()
    df["close"] = df["close"].astype(str)
    result = validate_schema(df, "korea", config.quality_config()["schema"])
    assert not result.passed


def test_empty_table_fails():
    import pandas as pd
    result = validate_schema(pd.DataFrame(), "korea", config.quality_config()["schema"])
    assert not result.passed


def test_none_fails():
    result = validate_schema(None, "korea", config.quality_config()["schema"])
    assert not result.passed
