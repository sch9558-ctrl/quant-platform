import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.scanner.scanner import DailyScanner, format_report


@pytest.fixture(scope="module")
def kr_provider():
    return SyntheticDataProvider(market="korea", n_symbols=30, n_etfs=4,
                                  start="2015-01-01", end="2023-12-31", seed=21)


@pytest.fixture(scope="module")
def us_provider():
    return SyntheticDataProvider(market="us", n_symbols=30, n_etfs=4,
                                  start="2015-01-01", end="2023-12-31", seed=22)


def test_korea_scan_end_to_end(kr_provider):
    scanner = DailyScanner("korea", kr_provider)
    result = scanner.run(as_of="2022-06-01", lookback_days=300, top_n=10)

    assert result.market == "korea"
    assert result.universe_size > 0
    assert len(result.top_candidates) <= 10
    assert result.regime is not None
    assert result.regime.trend_regime in ("bull", "bear", "sideways")


def test_us_scan_end_to_end(us_provider):
    scanner = DailyScanner("us", us_provider)
    result = scanner.run(as_of="2022-06-01", lookback_days=300, top_n=10)
    assert result.market == "us"
    assert len(result.all_candidates) >= len(result.top_candidates)


def test_format_report_produces_readable_text(kr_provider):
    scanner = DailyScanner("korea", kr_provider)
    result = scanner.run(as_of="2022-06-01", lookback_days=300, top_n=5)
    text = format_report(result)
    assert "Market Scan" in text
    assert "Top" in text
    assert isinstance(text, str) and len(text) > 50
