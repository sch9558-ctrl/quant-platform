import pandas as pd

from quant.features import fundamental as fnd


def _sample_fund_df():
    return pd.DataFrame({
        "per": [5.0, 10.0, 40.0, 15.0, 8.0],
        "pbr": [0.8, 1.5, 5.0, 2.0, 1.0],
        "roe": [0.20, 0.10, -0.05, 0.12, 0.18],
        "operating_margin": [0.25, 0.10, -0.02, 0.15, 0.20],
        "debt_ratio": [0.3, 0.8, 1.4, 0.6, 0.4],
        "eps_growth": [0.15, 0.05, -0.10, 0.08, 0.20],
        "revenue_growth": [0.10, 0.03, -0.05, 0.06, 0.12],
        "dividend_yield": [0.03, 0.01, 0.00, 0.02, 0.025],
        "market_cap": [1e9, 5e9, 2e10, 3e9, 8e8],
    }, index=["A", "B", "C", "D", "E"])


def test_value_score_prefers_cheap_stocks():
    df = _sample_fund_df()
    scores = fnd.value_score(df)
    # A has the lowest PER and PBR -> should have the highest (best) value score
    assert scores.idxmax() == "A"
    # C has the highest PER and PBR -> should have the lowest value score
    assert scores.idxmin() == "C"


def test_quality_score_prefers_high_roe_low_debt():
    df = _sample_fund_df()
    scores = fnd.quality_score(df)
    assert scores.idxmax() == "A"
    assert scores.idxmin() == "C"


def test_size_score_prefers_small_cap():
    df = _sample_fund_df()
    scores = fnd.size_score(df)
    assert scores.idxmax() == "E"  # smallest market cap
    assert scores.idxmin() == "C"  # largest market cap


def test_cross_sectional_zscore_zero_mean():
    df = _sample_fund_df()
    z = fnd.cross_sectional_zscore(df, columns=["roe"])
    assert abs(z["roe_z"].mean()) < 1e-9
