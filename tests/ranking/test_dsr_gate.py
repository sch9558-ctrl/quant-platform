from quant.ranking.scorer import StrategyFeatures, rank_strategies


def _features(strategy_id, dsr):
    return StrategyFeatures(
        strategy_id=strategy_id,
        market="korea",
        avg_is_cagr=.12,
        avg_oos_cagr=.10,
        avg_is_sharpe=1.0,
        avg_oos_sharpe=.9,
        avg_oos_sortino=1.1,
        avg_oos_calmar=.8,
        aggregate_oos_cagr=.10,
        aggregate_oos_sharpe=.9,
        aggregate_oos_mdd=-.10,
        stability_ratio=.9,
        n_oos_trades=80,
        n_folds=4,
        avg_turnover=.08,
        n_param_combos_tested=51,
        deflated_sharpe_probability=dsr,
    )


def test_dsr_probability_is_a_real_strategy_approval_gate():
    ranked=rank_strategies([
        _features("robust",.80),
        _features("data_mined",.30),
    ])
    assert bool(ranked.loc["robust","meets_minimum_requirements"]) is True
    assert bool(ranked.loc["data_mined","meets_minimum_requirements"]) is False
    assert ranked.loc["robust","deflated_sharpe_probability"]==.80
    assert ranked.loc["data_mined","n_param_combos_tested"]==51


def test_missing_dsr_keeps_backward_compatible_trade_fold_gate():
    ranked=rank_strategies([_features("legacy",None)])
    assert bool(ranked.loc["legacy","meets_minimum_requirements"]) is True


def test_cpcv_positive_sharpe_ratio_is_a_real_strategy_gate():
    robust=_features("cpcv_robust",.80)
    fragile=_features("cpcv_fragile",.80)
    robust.cpcv_positive_sharpe_ratio=.80
    fragile.cpcv_positive_sharpe_ratio=.40
    ranked=rank_strategies([robust,fragile])
    assert bool(ranked.loc["cpcv_robust","meets_minimum_requirements"]) is True
    assert bool(ranked.loc["cpcv_fragile","meets_minimum_requirements"]) is False
    assert ranked.loc["cpcv_robust","cpcv_positive_sharpe_ratio"]==.80
