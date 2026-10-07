"""Static Dashboard JSON export (spec sections 33-34).

Serializes a `ResearchPipelineResult` (from `run_full_pipeline`) plus a
`SystemStatus` (from `quant.quality.system_status`) into the flat JSON
files the static dashboard (`site/index.html`) reads:

    site/data/dashboard.json  -- today's full snapshot (overview, data
                                  quality, per-market candidates, strategy
                                  ranking, paper trading, risk checks,
                                  audit trail tail, provenance)
    site/data/history.json    -- one compact row appended per day (data
                                  quality pass, pipeline health, source
                                  disagreement/outlier counts, readiness
                                  level) for the 30/90/365-day trend
                                  section. Never raw prices -- safe for a
                                  public repo.

Deliberate simplification (documented, not hidden): this module computes
data-quality reports via SystemStatus (`compute_system_status`)
independently of the reports already produced inside
`run_full_pipeline`/`run_gated_scan` -- meaning the Data Quality Engine
runs twice per day (once for the research pipeline, once for the
dashboard's own status line). For a personal research platform run once a
day this extra cost is small and acceptable; unifying the two into a
single pass is a reasonable future optimization, not a correctness
requirement (both runs validate the exact same day's data through the
exact same gate, so they always agree).

ABSOLUTE RULE (spec section 0): nothing in this module may print or write
"100% safe", "guaranteed return", "no loss possible", or claim investment
prediction accuracy. Every dashboard payload carries the same
disclaimer text as the CLI tools.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant import config
from quant.analytics.trade_plan import build_trade_plan
from quant.pipeline.research_pipeline import MarketResearchResult, ResearchPipelineResult
from quant.dashboard_export import publishability
from quant.quality.readiness import DISCLAIMER
from quant.quality.system_status import SystemStatus
from quant.utils.logging import get_logger

logger = get_logger(__name__)

_MARKET_LABEL = {"korea": "국내 증시 (KOSPI/KOSDAQ)", "us": "미국 증시 (NYSE/NASDAQ/AMEX)"}

#: Never allowed anywhere in dashboard text (spec section 0/73) -- checked
#: by tests/dashboard_export/test_export.py so a future edit cannot
#: silently reintroduce one of these phrases.
FORBIDDEN_PHRASES = [
    # English
    "100% safe", "no loss possible", "100% profit", "100% accurate investment",
    "guaranteed return", "guaranteed profit", "cannot lose",
    # Korean -- the dashboard UI is Korean, and reason/summary strings that
    # reach this payload are written in Korean, so an English-only list would
    # let the exact same claim through in translation.
    "100% 안전", "손실 없음", "100% 수익", "수익 보장", "원금 보장",
    "무조건 수익", "절대 손실", "손실 위험 없",
]

#: The mandated disclaimer is the one sanctioned place where this vocabulary
#: legitimately appears -- its whole job is to *deny* these claims ("does not
#: mean ... that loss is impossible"). A substring scan cannot tell a claim
#: from its negation, so the disclaimer is removed before scanning rather
#: than the forbidden list being weakened to accommodate it.
_DISCLAIMER_EXEMPT = [DISCLAIMER]


def _candidate_to_dict(rank: int, c, institutional_overlay: dict | None = None) -> dict:
    edge = c.historical_signal_edge or {}
    return {
        "rank": rank,
        "symbol": c.symbol,
        "company": c.name,
        "market": c.market,
        "exchange": c.exchange,
        "asset_type": c.asset_type,
        "price": c.price,
        "momentum": c.momentum_rank,
        "trend": c.trend_score,
        "relative_strength": c.relative_strength,
        "volume": c.volume_score,
        "volatility": c.volatility,
        "fundamental_score": c.fundamental_score,
        "strategy_signal": c.signal,
        "risk_score": c.risk_score,
        "historical_signal_performance": {
            "n_obs": edge.get("n_obs", 0),
            "mean_fwd_20d_return": edge.get("mean_fwd_return"),
            "win_rate": edge.get("win_rate"),
        },
        "composite_score": c.composite_score,
        "price_history": list(getattr(c, "price_history", []) or []),
        "trade_plan": build_trade_plan(c),
        "institutional_overlay": institutional_overlay or {},
    }


def _strategy_validation_status(mrr: MarketResearchResult | None) -> str:
    """PASS / WARNING / FAIL -- deliberately NEVER a bare number (spec
    section 34: never hide problems behind a score)."""
    if mrr is None or mrr.blocked:
        return "FAIL"
    if mrr.ranking_df is None or mrr.ranking_df.empty:
        return "WARNING"
    for _, row in mrr.ranking_df.iterrows():
        if not row.get("meets_minimum_requirements", True):
            return "WARNING"
        if row.get("overfitting_warnings"):
            return "WARNING"
    return "PASS"


def _quality_quarantine_summary(mrr: MarketResearchResult | None) -> dict:
    if mrr is None or mrr.quality_report is None:
        return {"count": 0, "symbols": [], "reasons": [], "warning": False}
    missing = next(
        (c for c in mrr.quality_report.checks if c.check == "missing_sessions"),
        None,
    )
    if missing is None:
        return {"count": 0, "symbols": [], "reasons": [], "warning": False}
    details = missing.details or {}
    symbols = list(details.get("quarantined_symbols") or [])
    reasons = ["missing_sessions"] if symbols else []
    fraction = details.get("quarantine_fraction")
    warning_fraction = float(
        config.quality_config().get("missing_sessions", {}).get(
            "quarantine_warning_fraction", 0.15
        )
    )
    raw_passed = details.get("raw_passed")
    post_quarantine_pass = raw_passed is False and missing.passed is True
    history = dict(getattr(mrr, "quality_quarantine_history", {}) or {})
    warning = (
        fraction is not None and float(fraction) >= warning_fraction
    )
    return {
        "count": len(symbols),
        "symbols": symbols,
        "reasons": reasons,
        "reason_label_ko": "데이터 누락으로 제외된 종목" if symbols else None,
        "resolution": details.get("resolution"),
        "raw_passed": raw_passed,
        "post_quarantine_pass": post_quarantine_pass,
        "explanation_ko": (
            "원 missing_sessions 검사는 FAIL이었으나, 누락 종목 전체를 "
            "격리한 뒤 나머지 데이터가 필수 검증을 통과했습니다."
            if post_quarantine_pass else None
        ),
        "fraction": fraction,
        "max_fraction": details.get("max_symbol_quarantine_fraction"),
        "warning_fraction": warning_fraction,
        "warning": warning,
        "warning_ko": (
            f"품질 격리 비율이 사전 경고선 {warning_fraction:.0%} 이상입니다. "
            "시장 전체 차단 상한에 가까워지고 있으므로 공급자·유니버스 상태를 점검해야 합니다."
            if warning else None
        ),
        "consecutive_streaks": history.get("streaks", {}),
        "consecutive_alert_sessions": history.get("alert_sessions"),
        "consecutive_alert_symbols": history.get("alert_symbols", []),
    }


def _market_section(market: str, mrr: MarketResearchResult | None) -> dict:
    if mrr is None:
        return {"market": market, "label": _MARKET_LABEL[market], "status": "NO DATA", "blocked": True,
                "block_reason": "No result computed for this market in this run.", "candidates": []}
    if mrr.blocked:
        return {
            "market": market, "label": _MARKET_LABEL[market], "status": "DATA VALIDATION FAILED",
            "blocked": True, "block_reason": mrr.block_reason, "candidates": [],
            "universe_size": 0, "quality_quarantine": _quality_quarantine_summary(mrr),
            "candidate_diagnostics": {
                "candidate_count": 0,
                "scored_candidate_count": 0,
                "zero_candidate_stage": "DATA_QUALITY",
                "zero_candidate_reasons": [mrr.block_reason] if mrr.block_reason else [],
            },
            "institutional_overlay_summary": {"actions": {}, "reasons": {}},
        }
    scan = mrr.scan
    candidates = list(getattr(scan, "top_candidates", []) or [])
    all_candidates = list(getattr(scan, "all_candidates", []) or [])
    if candidates:
        zero_stage = None
        zero_reasons = []
    elif all_candidates:
        zero_stage = "TOP_N_SELECTION"
        zero_reasons = ["스코어링 후보는 존재하지만 최종 후보 선택 결과가 0개입니다."]
    else:
        zero_stage = "SCREENING"
        zero_reasons = ["검증된 유니버스에서 스크리닝/특징 계산 후 후보가 생성되지 않았습니다."]

    overlay_actions: dict[str, int] = {}
    overlay_reasons: dict[str, int] = {}
    for candidate in candidates:
        overlay = mrr.institutional_overlays.get(candidate.symbol) or {}
        action = str(overlay.get("action") or "UNKNOWN")
        overlay_actions[action] = overlay_actions.get(action, 0) + 1
        for reason in overlay.get("reasons") or []:
            key = str(reason)
            overlay_reasons[key] = overlay_reasons.get(key, 0) + 1

    return {
        "market": market, "label": _MARKET_LABEL[market], "status": "OK", "blocked": False, "block_reason": None,
        "as_of": str(scan.as_of.date()) if scan.as_of is not None else None,
        "regime": (
            {
                "summary": scan.regime.summary_label(),
                "trend_regime": scan.regime.trend_regime,
                "volatility_regime": scan.regime.volatility_regime,
                "risk_regime": scan.regime.risk_regime,
                "index_return_6m": scan.regime.index_return_6m,
                "index_vol_annualized": scan.regime.index_vol_annualized,
            } if scan.regime is not None else None
        ),
        "universe_size": scan.universe_size,
        "excluded_for_quality": len(scan.excluded_for_quality),
        "quality_quarantine": _quality_quarantine_summary(mrr),
        "candidate_diagnostics": {
            "candidate_count": len(candidates),
            "scored_candidate_count": len(all_candidates),
            "zero_candidate_stage": zero_stage,
            "zero_candidate_reasons": zero_reasons,
        },
        "institutional_overlay_summary": {
            "actions": dict(sorted(overlay_actions.items())),
            "reasons": dict(sorted(overlay_reasons.items())),
        },
        "candidates": [_candidate_to_dict(i, candidate, mrr.institutional_overlays.get(candidate.symbol)) for i, candidate in enumerate(candidates, 1)],
    }


def _strategy_rows(mrr: MarketResearchResult | None) -> list[dict]:
    """Note: `ranking_df` (built by `quant.ranking.scorer.rank_strategies`)
    only carries the *percentile scores* used to compute composite_score
    (return_score, oos_score, etc.) plus n_oos_trades/n_folds -- not the
    underlying raw OOS Sharpe/CAGR/MDD themselves. Those come straight from
    each strategy's own `WalkForwardResult.aggregate_oos_metrics`, the
    exact same object the CLI (`run_backtest.py`) prints -- so the
    dashboard and CLI always show identical numbers for the same run."""
    if mrr is None or mrr.blocked or mrr.ranking_df is None or mrr.ranking_df.empty:
        return []
    rows = []
    for strategy_id, row in mrr.ranking_df.iterrows():
        wf = mrr.walk_forward_results.get(strategy_id)
        agg = wf.aggregate_oos_metrics if wf is not None else None
        rows.append({
            "strategy_id": strategy_id,
            "market": row.get("market"),
            "composite_score": _safe_float(row.get("composite_score")),
            "meets_minimum_requirements": bool(row.get("meets_minimum_requirements", False)),
            "approval_state": row.get("approval_state"),
            "approval_reasons": list(row.get("approval_reasons") or []),
            "overfitting_warnings": list(row.get("overfitting_warnings") or []),
            "aggregate_oos_sharpe": _safe_float(agg.sharpe) if agg is not None else None,
            "aggregate_oos_sortino": _safe_float(agg.sortino) if agg is not None else None,
            "aggregate_oos_cagr": _safe_float(agg.cagr) if agg is not None else None,
            "aggregate_oos_mdd": _safe_float(agg.max_drawdown) if agg is not None else None,
            "aggregate_oos_calmar": _safe_float(agg.calmar) if agg is not None else None,
            "n_oos_trades": _safe_int(row.get("n_oos_trades")),
            "n_folds": _safe_int(row.get("n_folds")),
            "deflated_sharpe_probability": _safe_float(row.get("deflated_sharpe_probability")),
            "cpcv_positive_sharpe_ratio": _safe_float(row.get("cpcv_positive_sharpe_ratio")),
            "n_param_combos_tested": _safe_int(row.get("n_param_combos_tested")),
            "n_oos_return_observations": _safe_int(row.get("n_oos_return_observations")),
        })
    return sorted(rows, key=lambda r: (r["composite_score"] is None, -(r["composite_score"] or 0)))


def _backtest_rows(mrr: MarketResearchResult | None) -> list[dict]:
    if mrr is None or mrr.blocked:
        return []
    rows = []
    for strategy_id, wf in mrr.walk_forward_results.items():
        fold_rows = []
        for fr in wf.fold_results:
            fold_rows.append({
                "fold_id": fr.fold.fold_id,
                "is_period": [str(fr.fold.is_start.date()), str(fr.fold.val_end.date())],
                "oos_period": [str(fr.fold.oos_start.date()), str(fr.fold.oos_end.date())],
                "params": fr.chosen_params,
                "is_metrics": _metrics_to_dict(fr.is_metrics),
                "oos_metrics": _metrics_to_dict(fr.oos_metrics),
                "parameter_stable": fr.stability.is_stable if fr.stability is not None else None,
            })
        rows.append({
            "strategy_id": strategy_id,
            "n_folds": len(wf.fold_results),
            "folds": fold_rows,
            "aggregate_oos_metrics": _metrics_to_dict(wf.aggregate_oos_metrics),
        })
    return rows


def _metrics_to_dict(m) -> dict:
    if m is None:
        return {}
    return {
        "cagr": _safe_float(m.cagr), "sharpe": _safe_float(m.sharpe), "sortino": _safe_float(m.sortino),
        "max_drawdown": _safe_float(m.max_drawdown), "calmar": _safe_float(m.calmar),
        "num_trades": _safe_int(m.num_trades), "avg_turnover": _safe_float(m.avg_turnover),
    }


def _safe_float(v) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> int | None:
    try:
        if v is None or pd.isna(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _portfolio_section(mrr: MarketResearchResult | None) -> dict:
    if mrr is None or mrr.blocked or mrr.portfolio_allocation is None:
        return {"available": False, "weights": {}, "cash_weight": 1.0, "notes": []}
    a = mrr.portfolio_allocation
    return {
        "available": True,
        "weights": {str(k): _safe_float(v) for k, v in a.weights.items()},
        "cash_weight": _safe_float(a.cash_weight),
        "by_market": {str(k): _safe_float(v) for k, v in a.by_market.items()},
        "by_strategy": {str(k): _safe_float(v) for k, v in a.by_strategy.items()},
        "by_sector": {str(k): _safe_float(v) for k, v in a.by_sector.items()},
        "notes": list(a.notes),
    }


def _portfolio_risk_section(mrr: MarketResearchResult | None) -> dict:
    if mrr is None:
        return {"state": "NO_DATA", "reasons": ["시장 연구 결과 없음"]}
    state = dict(mrr.portfolio_risk_state or {})
    if not state:
        return {"state": "INSUFFICIENT_EVIDENCE", "reasons": ["포트폴리오 리스크 평가 결과 없음"]}
    return state


def _paper_trading_section(market: str, demo: bool, required_sessions: int = 250) -> dict:
    """Read-only snapshot of paper-broker state -- never submits an order.
    Session count is `len(equity_history)`, the number of real wall-clock
    daily equity marks actually recorded (spec: never backfilled/faked)."""
    from quant.broker.kr_paper import KoreaPaperBroker
    from quant.broker.us_paper import USPaperBroker

    broker = KoreaPaperBroker() if market == "korea" else USPaperBroker()
    curve = broker.get_equity_curve()
    if not curve.empty:
        curve = curve[~curve.index.duplicated(keep="last")].sort_index()
    sessions = int(len(curve))
    start_date = str(curve.index.min().date()) if sessions else None
    equity_tail = [
        {"date": pd.Timestamp(d).isoformat(), "equity": float(e)}
        for d, e in curve.tail(90).items()
    ]
    positions = {
        s: {"quantity": p.quantity, "avg_cost": p.avg_cost} for s, p in broker.get_positions().items()
    }
    return {
        "market": market,
        "cash": broker.get_cash(),
        "positions": positions,
        "n_positions": len(positions),
        "equity_history_tail": equity_tail,
        "sessions_completed": sessions,
        "sessions_required": required_sessions,
        "sessions_progress_label": f"{sessions}/{required_sessions}",
        "start_date": start_date,
        "progress_pct": round(min(1.0, sessions / required_sessions) * 100, 1),
        "validation_label_ko": (
            f"실데이터 페이퍼 검증 {sessions}/{required_sessions}거래일 / "
            f"시작일 {start_date or '아직 시작 전'}"
        ),
    }


def _audit_log_section(max_records: int = 200) -> list[dict]:
    """Tail of the append-only audit trail (spec section 15) -- read-only,
    never rewritten. Returns [] rather than raising if the audit log
    doesn't exist yet (e.g. a brand-new environment before the first
    validation run)."""
    from quant.quality.audit import AuditLog

    try:
        path = config.resolve_path(config.settings()["paths"]["db_dir"]) / "audit_log.jsonl"
        records = AuditLog(path).read_all()
    except Exception as e:  # noqa: BLE001 -- dashboard build must never crash on a missing/corrupt audit file
        logger.warning("Audit log section skipped: %s", e)
        return []
    return records[-max_records:]


def _validation_section(status: SystemStatus) -> dict:
    """A dedicated, self-contained view of "how do we know this is
    trustworthy" -- deliberately repeats data already present in
    `data_quality`/`overview` (built from the exact same SystemStatus
    object in the same call, so it can never disagree) so the dashboard's
    Validation tab doesn't need to cross-reference three other tabs."""
    return {
        "investment_readiness": {
            "level": status.readiness.level,
            "reasons": status.readiness.reasons,
            "disclaimer": status.readiness.disclaimer,
        },
        "test_buckets": {
            "unit_tests": status.label(status.unit_tests_pass),
            "integration_tests": status.label(status.integration_tests_pass),
            "regression_tests": status.label(status.regression_tests_pass),
        },
        "pipeline_health": "PASS" if status.pipeline_ok else "FAIL",
        "markets": {
            m: (report.summary() if (report := status.reports.get(m)) is not None else None)
            for m in status.markets
        },
    }


def _overview(markets: dict[str, MarketResearchResult], status: SystemStatus) -> dict:
    strategy_statuses = [_strategy_validation_status(m) for m in markets.values()]
    order = {"FAIL": 2, "WARNING": 1, "PASS": 0}
    strategy_validation = max(strategy_statuses, key=lambda s: order[s]) if strategy_statuses else "WARNING"

    quarantine = {
        market: _quality_quarantine_summary(result)
        for market, result in markets.items()
    }
    quarantine_count = sum(int(v.get("count") or 0) for v in quarantine.values())
    quarantine_alerts = sorted({
        symbol
        for v in quarantine.values()
        for symbol in (v.get("consecutive_alert_symbols") or [])
    })

    return {
        "data_integrity": "PASS" if status.data_quality_pass else "FAIL",
        "quality_quarantine_count": quarantine_count,
        "quality_quarantine_alert_symbols": quarantine_alerts,
        "quality_quarantine_note_ko": (
            f"데이터 누락으로 제외된 종목: {quarantine_count}개. "
            "격리된 종목은 후보·포트폴리오에서 완전히 제외됩니다."
            if quarantine_count else "데이터 누락으로 격리된 종목 없음"
        ),
        "mandatory_validation_pass_rate": (
            100.0 if status.data_quality_pass else 0.0
        ),
        "pipeline_health": "PASS" if status.pipeline_ok else "FAIL",
        "strategy_validation": strategy_validation,
        "investment_readiness": status.readiness.level,
        "investment_readiness_reasons": status.readiness.reasons,
        "unit_tests": status.label(status.unit_tests_pass),
        "integration_tests": status.label(status.integration_tests_pass),
        "regression_tests": status.label(status.regression_tests_pass),
        "disclaimer": DISCLAIMER,
    }


def build_dashboard_data(
    pipeline_result: ResearchPipelineResult,
    status: SystemStatus,
    demo: bool = True,
    generated_at: str | None = None,
) -> dict:
    markets = pipeline_result.markets
    overview = _overview(markets, status)

    data_quality = {
        market: (report.to_dict() if (report := status.reports.get(market)) is not None else None)
        for market in status.markets
    }

    market_sections = {m: _market_section(m, markets.get(m)) for m in ("korea", "us")}
    strategies = {m: _strategy_rows(markets.get(m)) for m in ("korea", "us")}
    backtests = {m: _backtest_rows(markets.get(m)) for m in ("korea", "us")}
    risk = {
        m: (markets[m].risk_checks if m in markets and not markets[m].blocked else [])
        for m in ("korea", "us")
    }
    portfolio = {m: _portfolio_section(markets.get(m)) for m in ("korea", "us")}
    portfolio_risk = {m: _portfolio_risk_section(markets.get(m)) for m in ("korea", "us")}
    paper_trading = {}
    for m in ("korea", "us"):
        try:
            paper_trading[m] = _paper_trading_section(m, demo=demo)
        except Exception as e:  # noqa: BLE001 -- dashboard build must never crash on a broker-state read
            logger.warning("Paper trading section skipped for %s: %s", m, e)
            paper_trading[m] = {"market": m, "error": "unavailable"}

    provenance = {
        m: (
            {
                "source": "SyntheticDataProvider (demo/offline mode)" if demo else "primary market data provider",
                "data_version": report.data_version,
                "checksum": report.checksum,
                "validation_status": report.overall_status,
                "generated_at": report.generated_at,
            } if (report := status.reports.get(m)) is not None else None
        )
        for m in ("korea", "us")
    }

    # How the data was produced has to travel WITH the payload, as a
    # machine-readable value. Previously `demo` only reached a
    # human-readable provenance string, so nothing downstream -- no check,
    # no test, no dashboard -- could tell synthetic prices from real ones.
    data_source_mode = publishability.SYNTHETIC if demo else publishability.REAL
    publish_report = publishability.assess(
        data_source_mode,
        {
            m: (
                pipeline_result.markets[m].as_of
                if m in pipeline_result.markets and pipeline_result.markets[m] is not None
                else None
            )
            for m in ("korea", "us")
        },
    )

    data = {
        "schema_version": 2,
        "generated_at": generated_at or pd.Timestamp.now(tz="UTC").isoformat(),
        "as_of": pipeline_result.as_of,
        "data_source_mode": data_source_mode,
        "publishability": publish_report.to_dict(),
        "overview": overview,
        "data_quality": data_quality,
        "markets": market_sections,
        "strategies": strategies,
        "backtests": backtests,
        "paper_trading": paper_trading,
        "risk": risk,
        "portfolio": portfolio,
        "portfolio_risk": portfolio_risk,
        "validation": _validation_section(status),
        "audit_log": _audit_log_section(),
        "provenance": provenance,
        "disclaimer": DISCLAIMER,
    }
    _assert_no_forbidden_phrases(data)
    return data


def _assert_no_forbidden_phrases(data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, default=str)
    for exempt in _DISCLAIMER_EXEMPT:
        text = text.replace(exempt, "")
    text = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in text:
            raise ValueError(
                f"Dashboard data contains a forbidden phrase ({phrase!r}) -- refusing to write it. "
                "See quant.dashboard_export.export.FORBIDDEN_PHRASES."
            )


def _history_row(data: dict) -> dict:
    """One compact row per day for the 30/90/365-day trend section --
    metrics only, never raw prices/candidates, so this file stays safe to
    commit to a public repo."""
    ov = data["overview"]
    outlier_counts = {
        m: (dq.get("outlier_counts") if dq else None) for m, dq in data["data_quality"].items()
    }
    return {
        "as_of": data["as_of"],
        "generated_at": data["generated_at"],
        # Carried into history so the trend section can never present a
        # synthetic or stale day as an ordinary passing day.
        "data_source_mode": data.get("data_source_mode"),
        "publishable": (data.get("publishability") or {}).get("publishable"),
        "freshness": {
            m: f.get("status")
            for m, f in ((data.get("publishability") or {}).get("markets") or {}).items()
        },
        "data_integrity": ov["data_integrity"],
        "pipeline_health": ov["pipeline_health"],
        "strategy_validation": ov["strategy_validation"],
        "investment_readiness": ov["investment_readiness"],
        "outlier_counts": outlier_counts,
        "n_source_mismatch": {
            m: (dq.get("checks_detail", []) and next(
                (c["issue_count"] for c in dq["checks_detail"] if c["check"] == "cross_source"), 0
            )) if dq else None
            for m, dq in data["data_quality"].items()
        },
        "historical_revisions": {
            m: (dq.get("checks_detail", []) and next(
                (c["issue_count"] for c in dq["checks_detail"] if c["check"] == "historical_revision"), 0
            )) if dq else None
            for m, dq in data["data_quality"].items()
        },
    }


def write_dashboard_json(data: dict, output_dir: Path, *, allow_unpublishable: bool = False) -> Path:
    """Write the production dashboard payload.

    Refuses synthetic or stale data unless `allow_unpublishable=True`,
    which exists for local development and for deliberately writing an
    honest DATA UNAVAILABLE state -- never for production publication.
    See `publishability` for why this gate exists.
    """
    report = publishability.PublishabilityReport(
        data_source_mode=data.get("data_source_mode", publishability.SYNTHETIC),
        markets={
            m: publishability.MarketFreshness(**f)
            for m, f in (data.get("publishability", {}).get("markets") or {}).items()
        },
        reasons=list((data.get("publishability", {}) or {}).get("reasons") or []),
    )
    if not allow_unpublishable:
        publishability.assert_publishable(report)
    elif not report.publishable:
        logger.warning(
            "Writing a NON-PUBLISHABLE dashboard payload (allow_unpublishable=True): %s",
            " / ".join(report.reasons),
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "dashboard.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def append_history(data: dict, output_dir: Path, max_days: int = 400) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "history.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    row = _history_row(data)
    # Idempotent: re-running the pipeline for a date already recorded
    # replaces that day's row instead of appending a duplicate.
    rows = [r for r in rows if r.get("as_of") != row["as_of"]]
    rows.append(row)
    rows = sorted(rows, key=lambda r: r["as_of"])[-max_days:]
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return path


def default_site_data_dir() -> Path:
    return config.resolve_path(config.settings()["paths"]["site_data_dir"])
