import pandas as pd
import pytest

from quant.data.synthetic_provider import SyntheticDataProvider
from quant.portfolio.constructor import PortfolioAllocation
from quant.report.daily_report import generate_daily_report, save_report
from quant.scanner.scanner import DailyScanner


@pytest.fixture(scope="module")
def kr_scan():
    provider = SyntheticDataProvider(market="korea", n_symbols=20, n_etfs=2,
                                      start="2016-01-01", end="2023-12-31", seed=51)
    scanner = DailyScanner("korea", provider)
    return scanner.run(as_of="2022-06-01", lookback_days=300, top_n=5)


def test_report_contains_all_required_sections(kr_scan):
    ranking_df = pd.DataFrame({
        "market": ["korea", "korea"],
        "composite_score": [0.8, 0.5],
        "meets_minimum_requirements": [True, False],
        "overfitting_warnings": [[], ["insufficient trades"]],
    }, index=pd.Index(["ma_crossover", "rsi_reversal"], name="strategy_id"))

    allocation = PortfolioAllocation(
        weights=pd.Series({"KEQ0001": 0.3, "KEQ0002": 0.2}),
        cash_weight=0.5, by_market={"korea": 0.5}, by_strategy={}, by_sector={},
    )

    report = generate_daily_report(
        as_of="2022-06-01", kr_scan=kr_scan, us_scan=None,
        strategy_ranking=ranking_df, portfolio_allocation=allocation,
    )

    assert "# Daily Research Report" in report
    assert "## Market Environment" in report
    assert "## Best Strategies" in report
    assert "## Korea Candidates" in report
    assert "## US Candidates" in report
    assert "## Portfolio Suggestions" in report
    assert "ma_crossover" in report
    assert "연구용" in report  # disclaimer present
    assert "Cash: 50%" in report


def test_report_handles_missing_composite_score_gracefully(kr_scan):
    # e.g. a manual `run_backtest.py --save` run that didn't compute a
    # cross-sectional composite score (only ranked among other strategies
    # does that make sense) -- must render "N/A" rather than raising.
    ranking_df = pd.DataFrame({
        "market": ["korea"],
        "composite_score": [None],
    }, index=pd.Index(["ma_crossover"], name="strategy_id"))

    report = generate_daily_report(as_of="2022-06-01", kr_scan=kr_scan, strategy_ranking=ranking_df)
    assert "Composite Score: N/A" in report


def test_report_handles_missing_data_gracefully():
    report = generate_daily_report(as_of="2022-06-01")
    assert "스캔 결과 없음" in report
    assert "전략 랭킹 결과 없음" in report
    assert "포트폴리오 제안 없음" in report


def test_save_report_writes_file(kr_scan, tmp_path, monkeypatch):
    from quant import config as quant_config
    original_settings = quant_config.settings()
    patched = {**original_settings, "paths": {**original_settings["paths"], "reports_dir": str(tmp_path)}}
    monkeypatch.setattr(quant_config, "settings", lambda: patched)

    report = generate_daily_report(as_of="2022-06-01", kr_scan=kr_scan)
    path = save_report(report, "2022-06-01")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == report
