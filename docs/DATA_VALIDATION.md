# Data Validation

This document describes the Data Quality Engine: what it checks, how a
result becomes PASS or FAIL, and how that result is wired into every
candidate-generating code path. It is the reference for spec sections
3-21 ("Data Quality Engine") and section 2 ("Fail-Closed").

## The one absolute principle

**Data Validation 100% and Investment Prediction Accuracy are two
different numbers and must never be conflated.**

"Data Validation 100%" means every mandatory data-quality check passed for
every symbol in that day's universe. It says nothing about whether any
strategy, ranking, or forecast built from that data will make money. The
disclaimer that ships with every readiness result (see
`docs/INVESTMENT_GATE.md`) exists specifically to keep these two ideas
separate on the dashboard, in reports, and in this codebase:

> "Data Validation 100% means all mandatory data-quality checks passed. It
> does not mean that future investment returns can be predicted with 100%
> accuracy or that loss is impossible."

## Two-tier metrics: binary vs. continuous

The engine reports two different numbers and callers must never merge
them:

- **`mandatory_validation_pass_rate`** (`DataQualityReport`, see
  `src/quant/quality/models.py`) is always exactly `0.0` or `100.0`, never
  a number in between. If even one mandatory check fails for even one
  symbol, this is `0.0` for the whole day/market — there is no partial
  credit ("99.99%도 FAIL이다"). This is the number that gates whether the
  pipeline is allowed to proceed (see "Fail-Closed" below).
- **`data_integrity_score`** is a continuous, informational-only score
  (outlier counts, review-vs-quarantine ratios, etc.). It is shown on the
  dashboard for diagnostic context but **never** used to decide
  `overall_status` or to unblock a failed mandatory check.

`DataQualityReport.overall_status` is `"PASS"` only when
`mandatory_validation_pass_rate == 100.0`.

## Mandatory checks

Configured in `config/quality.yaml` under `mandatory_checks`, implemented
one module per check under `src/quant/quality/`:

- `schema` (`schema.py`) — required columns present, correct dtypes,
  numeric columns actually numeric.
- `ohlc_integrity` (`ohlc.py`) — hard, non-configurable OHLC invariants
  (`high >= open, close, low`; `low <= open, close`; `volume >= 0`;
  `price > 0`), plus abnormal-return review/reject thresholds.
- `duplicates` (`completeness.py`) — no duplicate `(market, symbol, date)`
  rows.
- `missing_sessions` (`completeness.py`) — every real trading session
  (from the exchange's actual calendar, via `pandas_market_calendars`,
  not a weekday approximation) has a row for every symbol that was listed
  and not yet delisted, with listing/delisting dates as the only
  recognized exception (never a tolerance percentage).
- `freshness` (`completeness.py`) — data is current as of
  `max_lag_sessions` (0 by default) completed sessions, with a
  `grace_hours_after_close` window to avoid a false FAIL before a
  provider's EOD data is normally published.
- `timezone` (`completeness.py`) — dates are interpreted in the correct
  exchange timezone (`Asia/Seoul` for Korea, `America/New_York` for US),
  not silently coerced to UTC or the local machine's timezone.
- `corporate_action_consistency` (`corporate_actions.py`) — a large
  single-day price/volume jump must be explained by a known corporate
  action (split/dividend) within a grace window, or it fails.
- `cross_source` (`cross_source.py`) — the primary provider's OHLCV is
  compared against an independent secondary provider (see "Provider /
  Secondary-provider adapters" below); a large unexplained disagreement
  fails. Mandatory only when a secondary source actually returned data
  (`cross_source.require_secondary: false` in config) — a secondary
  source being unreachable is not itself made fatal, so a single
  provider's transient outage cannot silently block every market every
  day; when it IS available and disagrees beyond tolerance, that is
  fatal.

`historical_revision` (`engine.py`) is tracked but marked
`mandatory=False` — a provider silently revising already-published
history is logged and surfaced, but (deliberately) does not by itself
block the pipeline, since some revisions (e.g. a corrected split ratio)
are legitimate.

## Provider / secondary-provider adapters

Every market has a primary provider (`kr_provider.py` via `pykrx`,
`us_provider.py` via `yfinance`) and a secondary provider used only for
cross-checking (`kr_secondary_provider.py` via `finance-datareader`,
`us_secondary_provider.py` via Stooq's public CSV endpoint; both fall back
to a deterministic `SyntheticSecondaryProvider` in `--demo` mode). Neither
provider is trusted alone — `cross_source` is what catches the case where
one provider is simply wrong (bad tick, stale cache, misaligned
timestamp) but internally self-consistent.

## Canonical data

Once all mandatory checks pass, `DataQualityEngine.run()`
(`src/quant/quality/engine.py`) builds a single **canonical** OHLCV table
per symbol (`canonical.py`) — the one dataset every downstream stage
(universe, features, scanner, strategies, backtests) actually consumes.
`canonical_ohlcv_map` is returned **empty** when `overall_status == "FAIL"`
— callers must check `overall_status` before using it; there is no path
where a partially-valid canonical table is silently handed to a
downstream stage.

Every canonical record carries **provenance**: which source it came from,
data version, and checksum, so any number appearing later in a report or
on the dashboard can be traced back to the exact input row that produced
it (`AuditRecord` in `models.py`, `VersionStore` / `AuditLog` in
`audit.py`).

## Fail-Closed: from a report to a decision

`src/quant/quality/gate.py::may_proceed(report)` is the single, minimal
rule that turns a `DataQualityReport` into a go/no-go decision:

```python
def may_proceed(report: DataQualityReport) -> tuple[bool, str]:
    if report.overall_status != "PASS":
        return False, "DATA VALIDATION FAILED ... no investment candidates will be generated."
    return True, "Data validation PASSED ..."
```

Every caller that would otherwise generate today's candidates goes through
**`src/quant/quality/pipeline_gate.py::run_gated_scan()`**, not through a
raw provider or `DailyScanner` directly:

```
provider -> validate_market() -> DataQualityEngine -> DataQualityReport
                                        |
                                   may_proceed()
                                  /            \
                             blocked          allowed
                                |                |
                        GatedScanResult      DailyScanner.run(canonical data)
                        (scan=None)          GatedScanResult (scan=...)
```

`run_gated_scan()` is called from: `run_scan.py`, `run_paper.py`,
`run_backtest.py`, `generate_report.py`, and
`quant.pipeline.research_pipeline.run_market_research()` (which every
other pipeline entry point, including `run_research.py` and the daily
GitHub Actions workflow, goes through). A blocked market/day produces a
`GatedScanResult`/`MarketResearchResult` with `scan=None`,
`blocked=True`, and a human-readable `block_reason` — no candidate
ranking, no strategy evaluation, no portfolio construction, and no paper
trading order is generated for that market that day. This is enforced by
construction (there is no code path that reads `scan` without checking
`blocked` first — see `run_research.py`'s per-market loop and
`daily_report.py`'s block-banner rendering).

**Research failing is not the same as the dashboard failing to deploy.**
A blocked market still produces a report: the daily Markdown report
renders a distinct "⛔ DATA VALIDATION FAILED" section (never confused
with "스캔 결과 없음", the ordinary empty-candidates case), and the
static dashboard still builds and deploys, showing the block clearly. See
`.github/workflows/daily-pipeline.yml` and its inline comments for how
this is enforced at the CI level (`continue-on-error` on every pipeline
step, dashboard deploy job runs `if: always()`).

## Known-Answer Tests and Independent Verification

Per spec sections 55-59, `tests/known_answer/test_known_answer.py` holds
small, fixed, hand-computable datasets (a 10-day price series, a 5-value
return series, a 7-day equity curve, a single round-trip trade) whose
expected results were derived by hand arithmetic — not by calling the
library and asserting it agrees with itself — before being hardcoded as
assertions. This covers: 5-day SMA, cumulative return, max drawdown +
recovery days (including the "never recovers within the window" case,
which must return `None`, not a fabricated number), Korea/US round-trip
transaction cost (traced against `config/costs.yaml`'s documented rates),
and Sharpe/Sortino ratio.

Sharpe and Sortino additionally serve as **Independent Verification**: the
test computes each metric a second way, via a from-scratch numpy
calculation written directly in the test file (not reusing any part of
`quant.analytics.metrics`'s own implementation), and asserts the two agree
within a tight tolerance. A degenerate zero-variance return series is
tested explicitly to confirm the library returns `0.0`, never `NaN`/`inf`
that could otherwise leak into a report as a valid-looking number.

The rest of the required pytest coverage categories (Data Provider,
Schema, OHLC, Duplicate, Missing Date, Trading Calendar, Timezone,
Corporate Action, Cross Provider, Feature, Strategy, PnL, Transaction
Cost, Portfolio, Risk, Backtest, OOS, Dashboard Build) are covered across
`tests/quality/`, `tests/data/`, `tests/utils/`, `tests/backtest/`,
`tests/strategy/`, `tests/portfolio/`, `tests/risk/`,
`tests/validation/`, and `tests/dashboard_export/` — see
`docs/ARCHITECTURE.md`'s package layout for the corresponding source
module per test directory.

## Where this shows up on the dashboard

`quant.dashboard_export.export.build_dashboard_data()` renders both a
`data_quality` section (per-market `DataQualityReport.summary()`) and a
`validation` section that mirrors the same PASS/FAIL verdict shown in
Overview — deliberately redundant so the frontend never needs to
correlate across tabs to answer "did today's data pass?". See
`docs/INVESTMENT_GATE.md` for how this feeds the Investment Readiness
ladder, and the dashboard's required fields.
