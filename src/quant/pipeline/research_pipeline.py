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
from quant.portfolio.institutional import build_institutional_allocation
from quant.analytics.trade_plan import build_trade_plan
from quant.pipeline.institutional_overlay import evaluate_candidate
from quant.macro.cross_asset import fetch_cross_asset_snapshot
from quant.quality.models import DataQualityReport
from quant.quality.pipeline_gate import run_gated_scan
from quant.ranking.scorer import extract_features, rank_strategies
from quant.report.daily_report import generate_daily_report, save_report
from quant.research_db.db import ResearchDB
from quant.utils.calendar import default_as_of
from quant.research_db.models import ExperimentRecord, current_code_version, dataset_version_tag
from quant.risk.manager import PortfolioState, RiskManager
from quant.risk.filing_filter import FilingRiskService
from quant.risk.market_traps import MarketTrapDataService
from quant.risk_guard import RiskGuard
from quant.scanner.scanner import ScanResult
from quant.strategy import registry
from quant.utils.logging import get_logger
from quant.validation.walk_forward import WalkForwardAnalyzer, WalkForwardResult
from quant.broker.kr_paper import KoreaPaperBroker
from quant.broker.us_paper import USPaperBroker

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
    scan: ScanResult | None
    walk_forward_results: dict[str, WalkForwardResult]
    ranking_df: pd.DataFrame
    experiment_ids: list[str]
    new_strategy_ids: list[str]
    updated_strategy_ids: list[str]
    portfolio_allocation: PortfolioAllocation | None
    risk_checks: list[dict]
    portfolio_risk_state: dict = field(default_factory=dict)
    institutional_overlays: dict[str, dict] = field(default_factory=dict)
    quality_quarantine_history: dict = field(default_factory=dict)
    quality_report: DataQualityReport | None = None
    blocked: bool = False
    block_reason: str | None = None
    #: The session this market was actually analysed for. Recorded per
    #: market because the two markets legitimately differ: at 07:00 KST the
    #: latest closed Korean and US sessions are often different dates.
    as_of: str | None = None


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


def _record_quality_quarantine_history(
    db: ResearchDB,
    *,
    market: str,
    as_of: str,
    report: DataQualityReport,
) -> dict:
    """Persist and summarize whole-symbol quality quarantine for this session."""
    missing = next((x for x in report.checks if x.check == "missing_sessions"), None)
    details = dict((missing.details if missing is not None else {}) or {})
    quarantined = list(details.get("quarantined_symbols") or [])
    db.save_quality_quarantine_snapshot(
        market=market,
        session=as_of,
        quarantined_symbols=quarantined,
        resolution=details.get("resolution"),
        raw_passed=details.get("raw_passed", missing.passed if missing is not None else None),
        validation_pass=(report.overall_status == "PASS"),
        quarantine_fraction=details.get("quarantine_fraction"),
    )
    threshold = int(
        config.quality_config().get("missing_sessions", {}).get(
            "consecutive_quarantine_alert_sessions", 3
        )
    )
    return db.quality_quarantine_streaks(
        market=market,
        as_of=as_of,
        alert_sessions=threshold,
    )


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



def _aligned_candidate_returns(
    allocation: PortfolioAllocation,
    ohlcv_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    series = []
    for symbol, weight in allocation.weights.items():
        if float(weight) <= 0:
            continue
        frame = ohlcv_map.get(symbol)
        if frame is None or frame.empty or "close" not in frame:
            continue
        ret = pd.to_numeric(frame["close"], errors="coerce").pct_change().dropna()
        if not ret.empty:
            series.append(ret.rename(symbol))
    if not series:
        return pd.DataFrame()
    return pd.concat(series, axis=1, join="inner").replace([float("inf"), float("-inf")], pd.NA).dropna()


def _paper_nav(market: str) -> pd.Series:
    broker = KoreaPaperBroker() if market == "korea" else USPaperBroker()
    return broker.get_equity_curve()


def _portfolio_risk_analysis(
    market: str,
    allocation: PortfolioAllocation,
    ohlcv_map: dict[str, pd.DataFrame],
    *,
    nav: pd.Series | None = None,
    min_return_observations: int = 60,
) -> dict:
    guard = RiskGuard()
    returns = _aligned_candidate_returns(allocation, ohlcv_map)
    n_returns = int(len(returns))

    if n_returns >= min_return_observations:
        pvar, hvar = guard.value_at_risk(returns, weights=allocation.weights)
    else:
        pvar = hvar = None

    if nav is None:
        nav = _paper_nav(market)
    nav = pd.Series(nav, dtype=float).dropna() if nav is not None else pd.Series(dtype=float)

    reasons: list[str] = []
    if n_returns < min_return_observations:
        reasons.append(
            f"포트폴리오 수익률 관측치 부족: {n_returns} < 최소 {min_return_observations}"
        )
    if len(nav) < 2:
        reasons.append(
            f"운용 NAV 관측치 부족: {len(nav)} < 최소 2; 임의 NAV로 대체하지 않음"
        )

    if reasons:
        return {
            "state": "INSUFFICIENT_EVIDENCE",
            "var95_parametric": pvar,
            "var95_historical": hvar,
            "max_drawdown": None,
            "allow_new_entries": False,
            "liquidate_all": False,
            "return_observations": n_returns,
            "nav_observations": int(len(nav)),
            "reasons": reasons,
        }

    status = guard.evaluate(returns, nav, weights=allocation.weights)
    return {
        "state": status.action,
        "var95_parametric": status.var95_parametric,
        "var95_historical": status.var95_historical,
        "max_drawdown": status.max_drawdown,
        "allow_new_entries": status.allow_new_entries,
        "liquidate_all": status.liquidate_all,
        "return_observations": n_returns,
        "nav_observations": int(len(nav)),
        "reasons": [status.action],
    }


def _apply_portfolio_risk_to_scan(scan: ScanResult, state: dict) -> None:
    if bool((state or {}).get("liquidate_all")):
        scan.top_candidates = []


def _atr20_trailing_reference(frame: pd.DataFrame | None) -> float | None:
    if frame is None or frame.empty or len(frame) < 21:
        return None
    required = {"high", "low", "close"}
    if not required.issubset(frame.columns):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1).dropna()
    if len(tr) < 20:
        return None
    atr20 = float(tr.tail(20).mean())
    highest_high = float(high.tail(20).max())
    return RiskGuard.atr_trailing_stop(highest_high, atr20, multiple=2.5)


def run_market_research(
    market: str, demo: bool = True, as_of: str | None = None, top_n: int = 20,
    use_param_search: bool = False, lookback_years: int = DEFAULT_BACKTEST_LOOKBACK_YEARS,
    db: ResearchDB | None = None,
) -> MarketResearchResult:
    # Per market: at 07:00 KST the correct Korean and US sessions are
    # frequently different dates (see calendar.default_as_of).
    as_of = as_of or default_as_of(market)
    provider = get_provider(market, demo=demo)
    db = db or ResearchDB()
    filing_service = None if demo else FilingRiskService()
    market_trap_service = None if demo else MarketTrapDataService()

    # step 1 (Fail-Closed gate) + steps 2-5: Data Quality Engine -> universe
    # -> features -> regime -> screening, via the same DailyScanner used by
    # the dashboard/CLI scan commands, but fed the *validated, canonical*
    # OHLCV data instead of a fresh raw fetch. If the Data Quality Engine's
    # mandatory checks fail for this market/day, no candidates, no strategy
    # evaluation, and no risk analysis are produced -- the pipeline returns
    # a "blocked" result immediately (spec section 2: Fail-Closed). The
    # daily report / dashboard still render this result; they just show a
    # DATA VALIDATION FAILED state instead of candidates ("Research 실패 !=
    # Dashboard 배포 실패").
    gated = run_gated_scan(market, provider=provider, as_of=as_of, demo=demo, top_n=top_n)
    # From here on every calculation/report is dated to the bars actually used.
    as_of = gated.as_of
    quarantine_history = _record_quality_quarantine_history(
        db,
        market=market,
        as_of=as_of,
        report=gated.validation.report,
    )
    macro_snapshot = None if demo else fetch_cross_asset_snapshot(as_of)
    if gated.blocked:
        logger.error("Research pipeline BLOCKED for market=%s as_of=%s: %s", market, as_of, gated.block_reason)
        return MarketResearchResult(
            market=market, scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
            experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
            portfolio_allocation=None, risk_checks=[],
            portfolio_risk_state={"state": "DATA_VALIDATION_FAILED", "reasons": [gated.block_reason]},
            institutional_overlays={},
            quality_quarantine_history=quarantine_history,
            quality_report=gated.validation.report, blocked=True, block_reason=gated.block_reason,
            as_of=as_of,
        )
    scan = gated.scan
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
    member_by_symbol = {
        m.symbol: m for m in gated.validation.universe_snapshot.members
    }
    market_caps = {
        c.symbol: (
            member_by_symbol[c.symbol].market_cap
            if c.symbol in member_by_symbol else None
        )
        for c in scan.top_candidates
    }
    missing_caps = [
        symbol for symbol, value in market_caps.items()
        if value is None or float(value) <= 0
    ]
    if missing_caps:
        try:
            fetched_caps = provider.get_market_cap(missing_caps, as_of)
            for symbol in missing_caps:
                value = fetched_caps.get(symbol) if fetched_caps is not None else None
                if value is not None and pd.notna(value) and float(value) > 0:
                    market_caps[symbol] = float(value)
        except Exception as exc:
            logger.warning(
                "Selected-candidate market-cap enrichment skipped for %s: %s",
                market, exc,
            )
    signal_edges = {
        c.symbol: (c.historical_signal_edge or {})
        for c in scan.top_candidates
    }
    allocation, allocation_diag = build_institutional_allocation(
        items,
        gated.validation.canonical_ohlcv_map,
        market_caps=market_caps,
        signal_edges=signal_edges,
    )
    if allocation is None:
        allocation = PortfolioConstructor().compute_weights(items)
        allocation.notes.append(
            "institutional allocator unavailable: insufficient aligned return history; "
            "legacy constrained allocator used"
        )
    elif allocation_diag is not None:
        allocation.notes.append(
            "institutional diagnostics: "
            f"method={allocation_diag.method}, observations={allocation_diag.observations}, "
            f"views={allocation_diag.view_count}, prior={allocation_diag.prior_source}"
        )
    risk_checks = _risk_analysis(market, allocation)
    portfolio_risk_state = _portfolio_risk_analysis(
        market,
        allocation,
        gated.validation.canonical_ohlcv_map,
    )
    _apply_portfolio_risk_to_scan(scan, portfolio_risk_state)

    # Institutional safety/alpha overlay is part of the production research
    # result, not an orphan library. External filing/event feeds are still
    # wired separately; until they are available the overlay fails closed
    # with FILING_DATA_UNAVAILABLE rather than claiming risk clearance.
    institutional_overlays: dict[str, dict] = {}
    for candidate in scan.top_candidates:
        trade_plan = build_trade_plan(candidate)
        candidate_payload = {
            "market": market,
            "symbol": candidate.symbol,
            "price": candidate.price,
            "volatility": candidate.volatility,
            "composite_score": candidate.composite_score,
            "trade_plan": trade_plan,
        }
        filing_result = (
            filing_service.fetch(market, candidate.symbol, as_of=as_of)
            if filing_service is not None else None
        )
        filing_rows = (
            list(filing_result.filings)
            if filing_result is not None and filing_result.available
            else None
        )
        event_result = (
            market_trap_service.fetch(market, candidate.symbol, as_of=as_of)
            if market_trap_service is not None else None
        )
        event_available = bool(event_result is not None and event_result.available)
        market_frame = gated.validation.canonical_ohlcv_map.get(candidate.symbol)
        open_price = previous_close = None
        market_data_available = False
        if market_frame is not None and len(market_frame) >= 2:
            try:
                latest = market_frame.loc[:pd.Timestamp(as_of)].tail(2)
                if len(latest) >= 2:
                    open_price = float(latest["open"].iloc[-1])
                    previous_close = float(latest["close"].iloc[-2])
                    market_data_available = open_price > 0 and previous_close > 0
            except Exception:
                market_data_available = False

        macro_available = (
            macro_snapshot is not None and macro_snapshot.complete_for(market)
        )
        overlay = evaluate_candidate(
            candidate_payload,
            filings=filing_rows,
            as_of=as_of,
            earnings_date=(event_result.earnings_date if event_result else None),
            credit_balance_pct=(event_result.credit_balance_pct if event_result else None),
            open_price=open_price,
            previous_close=previous_close,
            usdkrw_1d_pct=(macro_snapshot.usdkrw_1d_pct if macro_snapshot else None),
            sox_1d_pct=(macro_snapshot.sox_1d_pct if macro_snapshot else None),
            vix=(macro_snapshot.vix if macro_snapshot else None),
            us10y_change_bp=(macro_snapshot.us10y_change_bp if macro_snapshot else None),
            macro_data_available=macro_available,
            market_data_available=market_data_available,
            event_data_available=event_available,
        ).to_dict()
        overlay["macro_snapshot"] = macro_snapshot.to_dict() if macro_snapshot is not None else None
        overlay["market_trap_inputs"] = {
            "open_price": open_price,
            "previous_close": previous_close,
            "earnings_date": (event_result.earnings_date if event_result else None),
            "credit_balance_pct": (event_result.credit_balance_pct if event_result else None),
            "event_source": (event_result.source if event_result else "demo_unavailable"),
            "event_error": (event_result.error if event_result else "demo mode"),
            "market_price_available": market_data_available,
            "event_data_available": event_available,
        }
        guard = RiskGuard()
        entry_mid = (
            float(trade_plan["entry_low"]) + float(trade_plan["entry_high"])
        ) / 2.0
        expected_reward = float(trade_plan["target_2"]) - entry_mid
        expected_risk = entry_mid - float(trade_plan["stop_loss"])
        rr_allowed = guard.entry_risk_reward_allowed(expected_reward, expected_risk)
        trailing_reference = _atr20_trailing_reference(market_frame)
        overlay["entry_risk_reward_allowed"] = rr_allowed
        overlay["atr_trailing_stop"] = trailing_reference
        if not rr_allowed:
            overlay["approved"] = False
            overlay["action"] = "REVIEW"
            overlay["risk_cleared"] = False
            overlay["reasons"] = list(overlay.get("reasons") or []) + [
                "ENTRY_RISK_REWARD_BELOW_MINIMUM"
            ]
        if not portfolio_risk_state.get("allow_new_entries", False):
            overlay["approved"] = False
            overlay["action"] = "REVIEW"
            overlay["risk_cleared"] = False
            overlay["reasons"] = list(overlay.get("reasons") or []) + [
                f"PORTFOLIO_RISK_{portfolio_risk_state.get('state', 'UNKNOWN')}"
            ]
        overlay["filing_source"] = (
            filing_result.source if filing_result is not None else "demo_unavailable"
        )
        overlay["filing_fetch_error"] = (
            filing_result.error if filing_result is not None else "demo mode"
        )
        overlay["filing_count"] = (
            len(filing_result.filings)
            if filing_result is not None and filing_result.available else 0
        )
        institutional_overlays[candidate.symbol] = overlay

    return MarketResearchResult(
        market=market, scan=scan, walk_forward_results=wf_results, ranking_df=ranking_df,
        experiment_ids=experiment_ids, new_strategy_ids=new_ids, updated_strategy_ids=updated_ids,
        portfolio_allocation=allocation, risk_checks=risk_checks,
        portfolio_risk_state=portfolio_risk_state,
        institutional_overlays=institutional_overlays,
        quality_quarantine_history=quarantine_history,
        quality_report=gated.validation.report, blocked=False, block_reason=None,
        as_of=as_of,
    )


def _safe_default_as_of(market: str) -> str | None:
    """`default_as_of` for a market that has already failed, without letting
    a calendar problem become a second failure on top of the first."""
    try:
        return default_as_of(market)
    except Exception:  # pragma: no cover - calendar data problem
        logger.warning("Could not resolve a session date for blocked market=%s", market)
        return None


def run_full_pipeline(
    demo: bool = True, as_of: str | None = None, top_n: int = 20,
    use_param_search: bool = False, markets: tuple[str, ...] = ("korea", "us"),
) -> ResearchPipelineResult:
    """Run the entire 10-step research pipeline for every requested market
    and assemble the combined Daily Research Report. This is exactly what
    `run_research.py` calls -- the single command described in the original
    spec (section 35)."""
    # Deliberately NOT resolved here. Leaving it None lets each market
    # resolve its own latest closed session; collapsing both markets onto
    # one date is what made the US market permanently one session stale.
    db = ResearchDB()

    market_results: dict[str, MarketResearchResult] = {}
    for market in markets:
        logger.info("Running research pipeline for market=%s as_of=%s", market, as_of)
        try:
            market_results[market] = run_market_research(
                market, demo=demo, as_of=as_of, top_n=top_n, use_param_search=use_param_search, db=db,
            )
        except Exception as e:
            # One market's data source being unreachable must not take the
            # other market down with it. KRX, for instance, does not answer
            # GitHub's runners at all: `list_symbols` raises before the
            # Fail-Closed gate ever gets a report to judge, and an
            # uncaught exception here discarded a completed US run along
            # with it.
            #
            # A provider outage is not a different *kind* of event from a
            # failed quality check -- both mean "no trustworthy data for
            # this market today" -- so it is recorded as the same blocked
            # result, with a reason that names the cause instead of a
            # traceback. The dashboard then renders this market as
            # explicitly unavailable rather than silently absent.
            logger.exception("Research pipeline could not run for market=%s", market)
            market_results[market] = MarketResearchResult(
                market=market, scan=None, walk_forward_results={}, ranking_df=pd.DataFrame(),
                experiment_ids=[], new_strategy_ids=[], updated_strategy_ids=[],
                portfolio_allocation=None, risk_checks=[], institutional_overlays={}, quality_report=None,
                blocked=True,
                block_reason=(
                    f"{market} 시장 데이터를 가져오지 못해 이 시장의 분석을 중단했습니다 "
                    f"(데이터 소스 접근 실패: {type(e).__name__}: {e}). "
                    "후보 종목·전략 평가·모의매매는 생성되지 않았습니다."
                ),
                # Still record which session this market *would* have been
                # analysed for, so a blocked market is dated like any other
                # rather than showing up undated next to a working one.
                as_of=as_of or _safe_default_as_of(market),
            )

    kr_result = market_results.get("korea")
    us_result = market_results.get("us")

    # The run-level label is the newest session any market was analysed for.
    # It is a label, not an input: each market's own `as_of` is what its
    # numbers actually describe, and the dashboard shows both.
    resolved = [r.as_of for r in market_results.values() if r is not None and r.as_of]
    as_of = max(resolved) if resolved else default_as_of(markets[0] if markets else "korea")

    # step 10: combined report. Uses whichever market's strategy ranking is
    # best overall (concatenated) and a merged portfolio allocation isn't
    # attempted across markets here (each market's own allocation is shown
    # separately in the report; a cross-market combined allocation is a
    # reasonable future extension once real capital needs to be split
    # between two brokerage accounts in two currencies).
    # `pd.concat([])` raises rather than returning an empty frame, and the
    # guard used to test `market_results` -- which is non-empty even when
    # every market inside it was blocked. So the one case this pipeline is
    # built around, every market Fail-Closed on the same day, crashed the
    # run-level assembly instead of producing the honest "no candidates"
    # report it is supposed to.
    rankings = [r.ranking_df for r in market_results.values()
                if r is not None and not r.ranking_df.empty]
    combined_ranking = pd.concat(rankings) if rankings else pd.DataFrame()

    report_text = generate_daily_report(
        as_of=as_of,
        kr_scan=kr_result.scan if kr_result else None,
        us_scan=us_result.scan if us_result else None,
        kr_block_reason=kr_result.block_reason if kr_result else None,
        us_block_reason=us_result.block_reason if us_result else None,
        strategy_ranking=combined_ranking if not combined_ranking.empty else None,
        portfolio_allocation=(kr_result.portfolio_allocation if kr_result and not kr_result.blocked else None) or (
            us_result.portfolio_allocation if us_result and not us_result.blocked else None
        ),
    )
    report_path = save_report(report_text, as_of)

    return ResearchPipelineResult(
        as_of=as_of, markets=market_results, report_text=report_text, report_path=str(report_path),
    )
