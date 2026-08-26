import pytest

from quant.portfolio.constructor import PortfolioConstraints, PortfolioConstructor, PortfolioItem


def _items():
    return [
        PortfolioItem("A", "korea", "momentum", sector="Tech", signal_strength=1.0, volatility=0.20),
        PortfolioItem("B", "korea", "momentum", sector="Tech", signal_strength=1.0, volatility=0.40),
        PortfolioItem("C", "us", "value", sector="Financials", signal_strength=2.0, volatility=0.10),
        PortfolioItem("D", "us", "value", sector="Financials", signal_strength=1.0, volatility=0.30),
    ]


def test_equal_weight_sums_correctly():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="equal_weight", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert alloc.weights.sum() == pytest.approx(1.0)
    assert all(abs(w - 0.25) < 1e-9 for w in alloc.weights)


def test_inverse_volatility_favors_low_vol_names():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="inverse_volatility", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert alloc.weights["C"] > alloc.weights["D"]  # C has lower vol (0.10 vs 0.30)
    assert alloc.weights["A"] > alloc.weights["B"]  # A has lower vol (0.20 vs 0.40)


def test_position_cap_enforced():
    constraints = PortfolioConstraints(max_position_weight=0.15, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="equal_weight", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert (alloc.weights <= 0.15 + 1e-9).all()
    assert "position weight cap applied" in alloc.notes


def test_sector_cap_enforced():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=0.3,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="equal_weight", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert alloc.by_sector["Tech"] <= 0.3 + 1e-9
    assert alloc.by_sector["Financials"] <= 0.3 + 1e-9


def test_min_cash_weight_enforced():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.4, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="equal_weight", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert alloc.cash_weight >= 0.4 - 1e-9


def test_market_cap_enforced():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=0.4,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="equal_weight", constraints=constraints)
    alloc = pc.compute_weights(_items())
    assert alloc.by_market["korea"] <= 0.4 + 1e-9
    assert alloc.by_market["us"] <= 0.4 + 1e-9


def test_empty_items_returns_all_cash():
    pc = PortfolioConstructor(method="equal_weight")
    alloc = pc.compute_weights([])
    assert alloc.weights.empty
    assert alloc.cash_weight == 1.0


def test_risk_parity_inversely_proportional_to_variance():
    constraints = PortfolioConstraints(max_position_weight=1.0, max_sector_weight=1.0,
                                        max_strategy_weight=1.0, max_market_weight=1.0,
                                        min_cash_weight=0.0, max_gross_exposure=1.0)
    pc = PortfolioConstructor(method="risk_parity", constraints=constraints)
    alloc = pc.compute_weights(_items())
    # C (vol 0.10) should get by far the largest weight since risk parity uses 1/variance
    assert alloc.weights["C"] == alloc.weights.max()
