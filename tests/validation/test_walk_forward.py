import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.validation.walk_forward import WalkForwardAnalyzer


@pytest.fixture(scope="module")
def data():
    provider = SyntheticDataProvider(market="korea", n_symbols=6, n_etfs=0,
                                      start="2010-01-01", end="2023-12-31", seed=44)
    symbols = [s.symbol for s in provider.list_symbols()]
    ohlcv_map = {s: provider.get_ohlcv(s, "2010-01-01", "2023-12-31") for s in symbols}
    return ohlcv_map


def test_walk_forward_without_param_search(data):
    analyzer = WalkForwardAnalyzer("korea")
    result = analyzer.run("ma_crossover", data, use_param_search=False)

    assert len(result.fold_results) >= 1
    for fr in result.fold_results:
        assert fr.chosen_params == {}
        assert fr.oos_metrics is not None
    assert not result.aggregate_oos_equity.empty


def test_walk_forward_with_param_search_picks_stable_params(data):
    analyzer = WalkForwardAnalyzer("korea")
    result = analyzer.run("ma_crossover", data, use_param_search=True)

    assert len(result.fold_results) >= 1
    for fr in result.fold_results:
        assert "fast_window" in fr.chosen_params
        assert "slow_window" in fr.chosen_params
        assert fr.stability is not None


def test_walk_forward_reports_is_and_oos_metrics_separately(data):
    analyzer = WalkForwardAnalyzer("korea")
    result = analyzer.run("rsi_reversal", data, use_param_search=False)
    fr = result.fold_results[0]
    assert fr.is_metrics.cagr is not None
    assert fr.oos_metrics.cagr is not None
