import pandas as pd

from quant.analytics.metrics import PerformanceMetrics
from quant.ranking.scorer import extract_features, rank_strategies
from quant.validation.splitter import Fold
from quant.validation.stability import StabilityResult
from quant.validation.walk_forward import FoldResult, WalkForwardResult


def _metrics(**overrides) -> PerformanceMetrics:
    base = dict(
        total_return=0.1, cagr=0.1, annual_vol=0.15, sharpe=0.8, sortino=1.0,
        max_drawdown=-0.15, calmar=0.67, profit_factor=1.5, win_rate=0.55,
        avg_win=0.03, avg_loss=-0.02, expectancy=0.01, avg_turnover=0.1,
        num_trades=50, avg_holding_period_days=15.0, exposure=0.6,
        max_drawdown_recovery_days=30,
    )
    base.update(overrides)
    return PerformanceMetrics(**base)


def _make_wf_result(strategy_id, market, fold_specs) -> WalkForwardResult:
    fold_results = []
    for i, (is_m, oos_m, stable) in enumerate(fold_specs):
        fold = Fold(i, pd.Timestamp("2015-01-01"), pd.Timestamp("2018-12-31"),
                    pd.Timestamp("2019-01-01"), pd.Timestamp("2019-12-31"),
                    pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"))
        stab = StabilityResult(params={"x": 1}, own_score=1.0, neighbor_avg_score=0.9,
                                neighbor_count=4, degradation_pct=0.1, is_stable=stable)
        fold_results.append(FoldResult(fold=fold, chosen_params={"x": 1}, is_metrics=is_m,
                                        oos_metrics=oos_m, stability=stab))
    agg_oos = fold_specs[-1][1]  # reuse last OOS metrics as a stand-in aggregate
    return WalkForwardResult(strategy_id=strategy_id, market=market, fold_results=fold_results,
                              aggregate_oos_equity=pd.Series([1.0, 1.1]), aggregate_oos_metrics=agg_oos)


def test_good_strategy_ranks_above_overfit_strategy():
    good = _make_wf_result("good_strat", "korea", [
        (_metrics(sharpe=1.0), _metrics(sharpe=0.9, cagr=0.12, max_drawdown=-0.08, num_trades=80, avg_turnover=0.05), True),
        (_metrics(sharpe=1.1), _metrics(sharpe=1.0, cagr=0.11, max_drawdown=-0.09, num_trades=90, avg_turnover=0.05), True),
    ])
    bad = _make_wf_result("bad_strat", "korea", [
        (_metrics(sharpe=2.5), _metrics(sharpe=0.05, cagr=-0.02, max_drawdown=-0.45, num_trades=8, avg_turnover=0.9), False),
        (_metrics(sharpe=2.8), _metrics(sharpe=-0.1, cagr=-0.05, max_drawdown=-0.5, num_trades=6, avg_turnover=0.95), False),
    ])

    features = [extract_features(good, n_param_combos_tested=5), extract_features(bad, n_param_combos_tested=60)]
    ranked = rank_strategies(features)

    assert ranked.index[0] == "good_strat"
    assert ranked.loc["good_strat", "composite_score"] > ranked.loc["bad_strat", "composite_score"]
    assert ranked.loc["bad_strat", "overfitting_warnings"]


def test_minimum_requirements_flag():
    thin = _make_wf_result("thin_strat", "korea", [
        (_metrics(), _metrics(num_trades=2), True),
    ])
    features = [extract_features(thin)]
    ranked = rank_strategies(features)
    assert ranked.loc["thin_strat", "meets_minimum_requirements"] == False


def test_extract_features_handles_no_folds():
    empty_wf = WalkForwardResult(strategy_id="empty", market="korea", fold_results=[],
                                  aggregate_oos_equity=pd.Series(dtype=float),
                                  aggregate_oos_metrics=_metrics(cagr=0, sharpe=0))
    feats = extract_features(empty_wf)
    assert feats.n_folds == 0
    assert feats.avg_oos_sharpe == 0.0


def test_rank_strategies_empty_input():
    assert rank_strategies([]).empty
