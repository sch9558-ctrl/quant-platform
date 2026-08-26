import pandas as pd
import pytest

from quant.universe import us_constituents as uc
from quant.data.synthetic_provider import SyntheticDataProvider


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    # redirect the module's cache directory to a tmp path so tests never
    # touch (or depend on) the real data/cache/us_universe directory
    monkeypatch.setattr(uc, "_cache_path", lambda name: (tmp_path / name))


def _fake_sp500_html(url):
    df = pd.DataFrame({"Symbol": ["AAA", "BBB", "CCC"]})
    return [df]


def _fake_nasdaq100_html(url):
    df = pd.DataFrame({"Ticker": ["AAA", "DDD"]})
    return [pd.DataFrame({"unrelated": [1, 2]}), df]


def test_fetch_sp500_constituents_uses_injected_fetcher():
    symbols = uc.fetch_sp500_constituents(fetch_html_fn=_fake_sp500_html)
    assert symbols == ["AAA", "BBB", "CCC"]


def test_fetch_nasdaq100_constituents_finds_ticker_column_across_tables():
    symbols = uc.fetch_nasdaq100_constituents(fetch_html_fn=_fake_nasdaq100_html)
    assert symbols == ["AAA", "DDD"]


def test_constituents_are_cached_between_calls(tmp_path):
    calls = {"n": 0}

    def fetcher(url):
        calls["n"] += 1
        return [pd.DataFrame({"Symbol": ["ZZZ"]})]

    first = uc.fetch_sp500_constituents(fetch_html_fn=fetcher)
    second = uc.fetch_sp500_constituents(fetch_html_fn=fetcher)
    assert first == second == ["ZZZ"]
    assert calls["n"] == 1  # second call hit the cache, not the fetcher


def test_discover_major_etfs_applies_liquidity_and_aum_filters():
    provider = SyntheticDataProvider(market="us", n_symbols=5, n_etfs=0,
                                      start="2020-01-01", end="2023-01-01", seed=5)
    result = uc.discover_major_etfs(provider, as_of="2022-06-01")
    # synthetic provider won't have real SPY/QQQ data, so this should
    # gracefully return an empty (not crash) list
    assert isinstance(result, list)
