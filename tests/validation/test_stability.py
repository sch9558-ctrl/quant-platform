from quant.validation import stability


def test_select_robust_params_prefers_plateau_over_isolated_spike():
    # window=49 is a huge isolated spike (48 and 50 are terrible); windows
    # 20-30 are a broad, moderately-good plateau. A naive "pick the best
    # score" selector would choose 49; the robust selector should not.
    def score_fn(window: int) -> float:
        if window == 49:
            return 5.0
        if window in (48, 50):
            return -3.0
        if 20 <= window <= 30:
            return 1.0
        return 0.2

    param_grid = {"window": list(range(10, 61))}
    results = stability.evaluate_param_grid(param_grid, lambda p: score_fn(p["window"]))

    chosen = stability.select_robust_params(results, perturbation_pct=0.15, max_degradation_pct=0.35)
    assert chosen is not None
    assert chosen.params["window"] != 49
    assert 20 <= chosen.params["window"] <= 30


def test_neighborhood_stability_flags_spike_as_unstable():
    def score_fn(window: int) -> float:
        return 5.0 if window == 49 else (-3.0 if window in (48, 50) else 1.0)

    param_grid = {"window": list(range(40, 60))}
    results = stability.evaluate_param_grid(param_grid, lambda p: score_fn(p["window"]))
    stab = stability.neighborhood_stability(results, perturbation_pct=0.05, max_degradation_pct=0.3)

    spike = next(s for s in stab if s.params["window"] == 49)
    assert spike.is_stable is False


def test_stability_frame_has_expected_columns():
    param_grid = {"a": [1, 2], "b": [10, 20]}
    results = stability.evaluate_param_grid(param_grid, lambda p: p["a"] + p["b"])
    df = stability.stability_frame(results)
    assert {"a", "b", "own_score", "neighbor_avg_score", "is_stable"}.issubset(df.columns)
    assert len(df) == 4
