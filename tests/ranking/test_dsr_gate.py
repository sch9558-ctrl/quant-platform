from quant.ranking.scorer import StrategyFeatures, rank_strategies


def _features(strategy_id, dsr, cpcv):
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
        cpcv_positive_sharpe_ratio=cpcv,
        n_oos_return_observations=120,
    )


def test_approval_requires_both_dsr_and_cpcv():
    ranked=rank_strategies([_features("approved",.80,.70)])
    row=ranked.loc["approved"]
    assert row["approval_state"]=="APPROVED"
    assert bool(row["meets_minimum_requirements"]) is True
    assert "모두 통과" in row["approval_reasons"][0]


def test_low_dsr_is_rejected_with_measured_value():
    ranked=rank_strategies([_features("low_dsr",.20,.70)])
    row=ranked.loc["low_dsr"]
    assert row["approval_state"]=="REJECTED"
    assert bool(row["meets_minimum_requirements"]) is False
    assert any("0.2000" in reason and "DSR" in reason for reason in row["approval_reasons"])


def test_missing_dsr_is_insufficient_evidence():
    ranked=rank_strategies([_features("missing_dsr",None,.70)])
    row=ranked.loc["missing_dsr"]
    assert row["approval_state"]=="INSUFFICIENT_EVIDENCE"
    assert bool(row["meets_minimum_requirements"]) is False
    assert any("DSR 산출 불가" in reason for reason in row["approval_reasons"])


def test_missing_both_dsr_and_cpcv_has_two_evidence_reasons():
    ranked=rank_strategies([_features("missing_both",None,None)])
    row=ranked.loc["missing_both"]
    assert row["approval_state"]=="INSUFFICIENT_EVIDENCE"
    assert bool(row["meets_minimum_requirements"]) is False
    missing=[r for r in row["approval_reasons"] if "산출 불가" in r]
    assert len(missing)==2
    assert any("DSR 산출 불가" in r for r in missing)
    assert any("CPCV 산출 불가" in r for r in missing)


def test_low_cpcv_is_rejected_with_measured_value():
    ranked=rank_strategies([_features("low_cpcv",.80,.40)])
    row=ranked.loc["low_cpcv"]
    assert row["approval_state"]=="REJECTED"
    assert bool(row["meets_minimum_requirements"]) is False
    assert any("0.4000" in reason and "CPCV" in reason for reason in row["approval_reasons"])
