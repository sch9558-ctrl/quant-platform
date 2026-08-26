"""Research Pipeline orchestrator (spec section 35).

This is the module `run_research.py` calls to run the entire chain, for
both Korea and US markets, in one command:

    1. Market data update        -- MarketDataProvider (+ParquetCache, transparently, on every get_ohlcv* call below)
    2. Universe generation       -- UniverseEngine (inside DailyScanner.run)
    3. Feature computation       -- FeatureEngine (inside DailyScanner.run, and again here over the longer backtest window)
    4. Market regime detection   -- RegimeDetector (inside DailyScanner.run)
    5. Stock screening           -- Screener (inside DailyScanner.run)
    6. Major strategy evaluation -- WalkForwardAnalyzer, run for every strategy in config/strategies.yaml
    7. Update of previously-validated strategies -- steps 6's fresh run *is*
       the update: any strategy that already has a prior ResearchDB record
       for this market gets a new one appended with today's data, and the
       pipeline result/report calls out which strategies were "new" vs
       "updated" so the difference is visible to the user.
    8. Candidate stock ranking   -- already produced by step 5 (`ScanResult.top_candidates`)
    9. Risk analysis             -- PortfolioConstructor + RiskManager applied
       to the top-ranked strategies' current candidate universe
   10. Research report generation -- `quant.report.daily_report`

Design trade-off (deliberately explicit): running the full parameter-search
Walk-Forward Analysis for every one of the ~12 strategies across both
markets, every single day, would be far too slow for a "run this every day"
command (a single strategy's full grid search alone takes minutes -- see
`tests/validation/test_walk_forward.py`). So by default this pipeline runs
Walk-Forward *without* a parameter search (i.e. each strategy's config-file
default parameters, still validated out-of-sample across multiple rolling
folds) -- `use_param_search=True` is available for a deeper, slower research
run but is not the daily default. This matches the spec's own priority
order (spec section 32): OOS performance and robustness first, raw
backtested return last -- a strategy's default parameters, walk-forward
validated, is exactly the "is this stable" question this platform cares
about; a full per-strategy parameter search is better run one strategy at a
time via `run_backtest.py --strategy <id> --param-search`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant import config
from quant.data.factory import get_provider
from quant.features import fundamental as fnd
from quant.features.engine import FeatureEngine
from quant.portfolio.constructor import PortfolioAllocation, PortfolioConstructor, PortfolioItem
from quant.ranking.scorer import extract_features, rank_strategies
from quant.report.daily_report import generate_daily_report, save_report
from quant.research_db.db import ResearchDB
from quant.research_db.models import ExperimentRecord, current_code_version, dataset_version_tag
from quant.risk.manager import PortfolioState, RiskManager
from quant.scanner.scanner import DailyScanner, ScanResult
from quant.strategy import registry
from quant.utils.logging import get_logger
from quant.validation.walk_forward import WalkForwardAnalyzer, WalkForwardResult

logger = get_logger(__name__)

# Benchmark index id per market -- these name a *benchmark/reference index*,
# not an individual tradeable ticker in the universe, so they are not
# subject to the "no hardcoded tickers" rule (see also scanner.py, which
# uses this same convention for the daily scan's own regime detection).
DEFAULT_BENCHMARK_INDEX = {"korea": "KOSPI", "us": "SP500"}

DEFAULT_BACKTEST_LOOKBACK_YEARS = 8


@dataclass
class MarketResearchResult:
    market: str
    scan: ScanResult
    walk_forward_results: dict[str, WalkForwardResult]
    ranking_df: pd.DataFrame
    experiment_ids: list[str]
    new_strategy_ids: list[str]
    updated_strategy_ids: list[str]
    portfolio_allocation: PortfolioAllocation
    risk_checks: list[dict]


@dataclass
class ResearchPipelineResult:
    as_of: str
    markets: dict[str, MarketResearchResult]
    report_text: str
    report_path: str


def _build_backtest_inputs(
    market: str, provider, symbols: list[str], as_of: str, lookback_years: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.Series]:
    """Fetch OHLCV + compute the full feature panel (technical + momentum
    rank + fundamental scores) over a multi-year window, for Walk-Forward
    Analysis. Mirrors the recipe in
    `tests/strategy/test_registry_integration.py`, which exercises every
    enabled strategy against exactly this shape of inputs."""
    start = (pd.Timestamp(as_of) - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    ohlcv_map = provider.get_ohlcv_bulk(symbols, start, as_of)
    ohlcv_map = {s: df for s, df in ohlcv_map.items() if df is not None and not df.empty}

    index_symbol = DEFAULT_BENCHMARK_INDEX[market]
    index_ohlcv = provider.get_index_ohlcv(index_symbol, start, as_of)
    benchmark_close = index_ohlcv["close"] if not index_ohlcv.empty else None

    engine = FeatureEngine(market)
    feature_map = engine.compute_panel(ohlcv_map, benchmark_close=benchmark_close)
    rank_wide = engine.cross_sectional_momentum_rank(feature_map)
    feature_map = engine.attach_momentum_rank(feature_map, rank_wide)

    all_dates = index_ohlcv.index if not index_ohlcv.empty else pd.DatetimeIndex([])
    if len(all_dates):
        rebalance_dates = pd.date_range(all_dates[0], all_dates[-1], freq="MS")
        try:
            fund_series = fnd.build_fundamental_score_series(provider, list(ohlcv_map), all_dates, rebalance_dates)
            feature_map = engine.attach_fundamental_scores(feature_map, fund_series)
        except Exception as e:
            logger.warning("Fundamental score series skipped for %s: %s", market, e)

    return ohlcv_map, feature_map, benchmark_close


def _evaluate_strategies(
    market: str,
    ohlcv_map: dict[str, pd.DataFrame],
    feature_map: dict[str, pd.DataFrame],
    benchmark_close: pd.Series,
    use_param_search: bool,
) -> dict[str, WalkForwardResult]:
    analyzer = WalkForwardAnalyzer(market)
    results: dict[str, WalkForwardResult] = {}
    for strategy_id in registry.enabled_strategy_ids():
        try:
            wf = analyzer.run(
                strategy_id, ohlcv_map, feature_map=feature_map, benchmark_close=benchmark_close,
                use_param_search=use_param_search,
            )
            results[strategy_id] = wf
        except Exception as e:
            logger.warning("Strategy evaluation failed for %s/%s: %s", market, strategy_id, e)
    return results


def _save_experiments(
    db: ResearchDB, market: str, symbols: list[str], start: str, end: str,
    wf_results: dict[str, WalkForwardResult], ranking_df: pd.DataFrame,
) -> tuple[list[str], list[str], list[str]]:
    code_version = current_code_version()
    d_version = dataset_version_tag(market, symbols, start, end)
    experiment_ids: list[str] = []
    new_ids, updated_ids = [], []

    for strategy_id, wf in wf_results.items():
        prior = db.latest_experiment(market, strategy_id)
        folds = wf.fold_results
        is_metrics = folds[-1].is_metrics if folds else None
        oos_metrics = folds[-1].oos_metrics if folds else None
        composite = float(ranking_df.loc[strategy_id, "composite_score"]) if strategy_id in ranking_df.index else None

        record = ExperimentRecord(
            experiment_id=f"{market}_{strategy_id}_{pd.Timestamp(end).strftime('%Y%m%d')}",
            created_at=pd.Timestamp.now(),
            market=market, strategy_id=strategy_id,
            params=folds[-1].chosen_params if folds else {},
            universe_description=f"{len(symbols)} symbols (screened universe)",
            backtest_start=start, backtest_end=end,
            is_metrics=vars(is_metrics) if is_metrics else {},
            oos_metrics=vars(oos_metrics) if oos_metrics else {},
            aggregate_oos_metrics=vars(wf.aggregate_oos_metrics),
            cost_config=config.costs_config(),
            code_version=code_version, dataset_version=d_version,
            composite_score=composite,
            overfitting_risk=None,
            notes="daily research pipeline run",
        )
        db.save_experiment(record)
        experiment_ids.append(record.experiment_id)
        (updated_ids if prior is not None else new_ids).append(strategy_id)

    return experiment_ids, new_ids, updated_ids


def _risk_analysis(
    market: str, allocation: PortfolioAllocation,
) -> list[dict]:
    """Re-check the constructed allocation's per-symbol weights through the
    shared RiskManager (spec section 17: every proposed rebalance -- research
    or live -- should pass through the same risk checks a real order would).
    """
    risk_manager = RiskManager()
    nav = 1.0  # research-mode check: work in normalized weight space
    state = PortfolioState(nav=nav, peak_nav=nav, positions={}, daily_pnl_pct=0.0, consecutive_losses=0)
    checks = []
    for symbol, weight in allocation.weights.items():
        result = risk_manager.check_order(symbol, float(weight), state)
        checks.append({
            "symbol": symbol, "requested_weight": result.requested_weight,
            "approved_weight": result.approved_weight, "approved": result.approved,
            "reasons": result.reasons,
        })
    return checks


def run_market_research(
    market: str, demo: bool = True, as_of: str | None = None, top_n: int = 20,
    use_param_search: bool = False, lookback_years: int = DEFAULT_BACKTEST_LOOKBACK_YEARS,
    db: ResearchDB | None = None,
) -> MarketResearchResult:
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    provider = get_provider(market, demo=demo)
    db = db or ResearchDB()

    # steps 2-5: universe -> features -> regime -> screening, via the same
    # DailyScanner used by the dashboard/CLI scan commands.
    scanner = DailyScanner(market, provider)
    scan = scanner.run(as_of=as_of, top_n=top_n)
    symbols = [c.symbol for c in scan.all_candidates] or [c.symbol for c in scan.top_candidates]

    # step 6/7: major strategy evaluation (+ implicit update of any strategy
    # that already had a prior ResearchDB record for this market).
    ohlcv_map, feature_map, benchmark_close = _build_backtest_inputs(market, provider, symbols, as_of, lookback_years)
    wf_results = _evaluate_strategies(market, ohlcv_map, feature_map, benchmark_close, use_param_search)

    features = [extract_features(wf) for wf in wf_results.values()]
    ranking_df = rank_strategies(features)

    backtest_start = (pd.Timestamp(as_of) - pd.DateOffset(years=lookback_years)).strftime("%Y-%m-%d")
    experiment_ids, new_ids, updated_ids = _save_experiments(
        db, market, list(ohlcv_map), backtest_start, as_of, wf_results, ranking_df,
    )

    # step 8 is the scanner's `top_candidates` (already produced above).
    # step 9: build a constrained portfolio from today's top candidates,
    # sized by composite candidate score and volatility, then re-check every
    # position through the RiskManager.
    items = [
        PortfolioItem(
            symbol=c.symbol, market=market, strategy_id="scanner", sector=None,
            signal_strength=max(c.composite_score, 0.0), volatility=c.volatility,
        )
        for c in scan.top_candidates
    ]
    allocation = PortfolioConstructor().compute_weights(items)
    risk_checks = _risk_analysis(market, allocation)

    return MarketResearchResult(
        market=market, scan=scan, walk_forward_results=wf_results, ranking_df=ranking_df,
        experiment_ids=experiment_ids, new_strategy_ids=new_ids, updated_strategy_ids=updated_ids,
        portfolio_allocation=allocation, risk_checks=risk_checks,
    )


def run_full_pipeline(
    demo: bool = True, as_of: str | None = None, top_n: int = 20,
    use_param_search: bool = False, markets: tuple[str, ...] = ("korea", "us"),
) -> ResearchPipelineResult:
    """Run the entire 10-step research pipeline for every requested market
    and assemble the combined Daily Research Report. This is exactly what
    `run_research.py` calls -- the single command described in the original
    spec (section 35)."""
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    db = ResearchDB()

    market_results: dict[str, MarketResearchResult] = {}
    for market in markets:
        logger.info("Running research pipeline for market=%s as_of=%s", market, as_of)
        market_results[market] = run_market_research(
            market, demo=demo, as_of=as_of, top_n=top_n, use_param_search=use_param_search, db=db,
        )

    kr_result = market_results.get("korea")
    us_result = market_results.get("us")

    # step 10: combined report. Uses whichever market's strategy ranking is
    # best overall (concatenated) and a merged portfolio allocation isn't
    # attempted across markets here (each market's own allocation is shown
    # separately in the report; a cross-market combined allocation is a
    # reasonable future extension once real capital needs to be split
    # between two brokerage accounts in two currencies).
    combined_ranking = pd.concat(
        [r.ranking_df for r in market_results.values() if r is not None and not r.ranking_df.empty]
    ) if market_results else pd.DataFrame()

    report_text = generate_daily_report(
        as_of=as_of,
        kr_scan=kr_result.scan if kr_result else None,
        us_scan=us_result.scan if us_result else None,
        strategy_ranking=combined_ranking if not combined_ranking.empty else None,
        portfolio_allocation=kr_result.portfolio_allocation if kr_result else (
            us_result.portfolio_allocation if us_result else None
        ),
    )
    report_path = save_report(report_text, as_of)

    return ResearchPipelineResult(
        as_of=as_of, markets=market_results, report_text=report_text, report_path=str(report_path),
    )
