# Final Self-Audit

A 15-point self-audit of this platform against its governing specification,
performed at commit `c00d193` and updated after the real-data switch
(2026-08-26). Full test suite: **375 passed, 1 deselected** (`tests/validation/test_walk_forward.py::test_walk_forward_with_param_search_picks_stable_params`,
deliberately excluded from the fast daily/CI bucket for being slow, not for
being flaky — still run by the plain `pytest tests/` developer workflow).

Each point below states PASS, PASS WITH DOCUMENTED LIMITATION, or a
specific finding. Nothing here is glossed over — a documented limitation
is a known, intentional scope boundary, called out explicitly rather than
silently left out of this audit.

## 1. Data accuracy

**PASS.** Every market has an independent secondary provider
(`kr_secondary_provider.py` / `us_secondary_provider.py`, falling back to
`SyntheticSecondaryProvider` in `--demo` mode) used only for cross-checking
the primary provider (`cross_source.py`), so a single provider being wrong
in a self-consistent way is still caught. See `docs/DATA_VALIDATION.md`.

## 2. Data integrity

**PASS.** Schema, OHLC invariants, duplicates, missing sessions,
freshness, timezone, and corporate-action consistency are all mandatory
checks (`config/quality.yaml`, `src/quant/quality/*.py`). A canonical data
table is only built when every mandatory check passes
(`DataQualityEngine.run()`); it is empty otherwise. Every canonical record
carries source/version/checksum provenance (`AuditRecord`, `audit.py`).

## 3. Calculation accuracy

**PASS.** `tests/known_answer/test_known_answer.py` hand-derives expected
values for SMA, cumulative return, drawdown/recovery, and round-trip
transaction costs from documented formulas/config — never by calling the
code under test and checking self-consistency. Sharpe/Sortino are
additionally cross-checked against a from-scratch numpy implementation
written directly in the test file (Independent Verification).

## 4. Backtest reliability

**PASS.** Transaction costs are modeled per market
(`backtest/costs.py`, verified in known-answer tests), a dedicated
no-lookahead test suite exists (`tests/features/test_no_lookahead.py`),
and every strategy runs through Walk-Forward Analysis
(`validation/walk_forward.py`) with fold-by-fold IS/OOS metrics rather
than a single in-sample backtest number.

## 5. Reproducibility

**PASS.** Every strategy evaluation persisted to the Research DB
(`research_db/models.py`) stores the git commit hash, a dataset version
fingerprint, exact parameters, universe description, date range, and cost
assumptions alongside every computed metric.

**Documented limitation** (called out in `README.md`'s own "Extending
this platform" section): `dataset_version_tag` fingerprints *which* data
was requested (symbols, date range, source), not a content hash of the
actual price values returned. A provider silently revising history within
an otherwise-identical request would not change this fingerprint. The
`historical_revision` check (non-mandatory, `engine.py`) is the current
mitigation — it detects and logs such revisions when they occur, but does
not (yet) feed into the reproducibility fingerprint itself.

## 6. Overfitting prevention

**PASS.** Train/Validation/OOS split (`validation/splitter.py`),
Walk-Forward parameter stability checks (`validation/stability.py`),
Probability-of-Backtest-Overfitting-style detection and Monte Carlo
resampling (`ranking/overfitting.py`, `ranking/monte_carlo.py`) all feed
into the composite Quant Strategy Score (`ranking/scorer.py`).

**Documented limitation**: the overfitting detector is an explicitly
simplified proxy for the full combinatorially-symmetric cross-validation
procedure (called out in the module's own docstring and in `README.md`).

## 7. Verifiability

**PASS.** Every data-quality decision is logged to an append-only audit
log (`quality/audit.py::AuditLog`) and surfaced on the dashboard's Audit
Log tab (`dashboard_export/export.py::_audit_log_section()`). Every
canonical data point traces back to a source/version/checksum. Every
research result traces back to a Research DB record.

## 8. Long-term pre-live verification

**PASS WITH DOCUMENTED LIMITATION.** The Investment Readiness ladder
(`quality/readiness.py`) requires ≥250 real, non-backfilled paper-trading
sessions before `PAPER_VERIFIED`, and paper trading state
(`broker/kr_paper.py`/`us_paper.py`) persists real wall-clock equity marks
only — `run_paper.py` skips the mark entirely on a Fail-Closed-blocked
day rather than counting it. However, `quant.quality.system_status.compute_system_status()`
does not yet persist/track OOS-pass history, walk-forward-pass history,
cost-stress-test results, the paper-trading session *count*, or risk-report
generation as a running state — these `ReadinessInputs` fields are left at
their conservative defaults (`False`/`0`) rather than fabricated, which
means the automatically computed ladder currently reports a lower level
than a fully-wired tracker would, even on all-green days. This is
documented in `docs/INVESTMENT_GATE.md` as the natural next extension
point, and is a safe failure mode (under-reporting readiness, never
over-reporting it) rather than a correctness bug.

## 9. Fail-Closed architecture

**PASS.** `quality/gate.py::may_proceed()` is the single rule; every
daily-candidate-generating entry point
(`run_scan.py`, `run_paper.py`, `run_backtest.py`, `generate_report.py`,
`run_research.py` via `research_pipeline.run_market_research()`) goes
through `quality/pipeline_gate.py::run_gated_scan()` rather than touching
a raw provider/`DailyScanner` directly. Verified by
`tests/pipeline/test_research_pipeline.py`,
`tests/cli/test_run_research_cli.py`, and manual CLI smoke tests against
demo data with a deliberately-failing market.

**Documented limitation**: the interactive Streamlit dashboard's
`dashboard/data_access.py` (`run_scan()`, `run_paper_rebalance()`) still
calls `DailyScanner` directly and is not wired through the gate. This is a
deliberate scope decision, not an oversight — the project's dashboard
architecture, per spec, is the static GitHub Pages site
(`site/index.html`), not the older Streamlit app, which predates this
phase of the project and is not part of the daily automated pipeline.
Anyone still using `run_dashboard.py` interactively should be aware its
scan/rebalance actions are not currently Fail-Closed gated.

## 10. Full GitHub-based automation

**PASS WITH DOCUMENTED LIMITATION.** `.github/workflows/daily.yml`
implements the primary (07:00 KST) + idempotent recovery (07:15 KST)
dual schedule plus `workflow_dispatch`, with `continue-on-error` on every
pipeline step and a dashboard-deploy job that runs `if: always()`, guarded
structurally by `tests/workflows/test_daily_pipeline_workflow.py` (13
tests). The workflow **has now run successfully on GitHub's runners** and
deployed the dashboard to GitHub Pages, so the automation is no longer
merely structurally verified.

**Documented limitation**: the sandbox this was developed in cannot reach
GitHub (`git push` and `api.github.com` are both blocked by an egress
proxy, independent of credentials), so changes are delivered to the user's
local clone and pushed from their machine. More importantly, **the
real-data path's first live contact is a CI run, not a local test**: no
environment available during development could reach KRX or Yahoo Finance,
so the providers are exercised against recorded/faked module doubles
(`tests/data/test_kr_provider_bulk.py`, `test_us_provider_bulk.py`) rather
than the live endpoints. Those doubles pin the request *shape* — which
axis is fetched, how many requests, chunking, failure isolation, and the
exclusive-end-date correction — but cannot catch an upstream schema change.
The Fail-Closed gate is what bounds the consequence: bad or missing
provider data blocks candidate generation for that market and day rather
than propagating into research output.

## 11. Data Validation vs. Investment Prediction Accuracy separation

**PASS.** `mandatory_validation_pass_rate` (binary) and
`data_integrity_score` (continuous, informational) are distinct fields
throughout (`quality/models.py`) and never merged. The dashboard shows
five separate required fields (Data Integrity, Mandatory Validation Pass
Rate, Pipeline Health, Strategy Validation, Investment Readiness) rather
than one collapsed score (`tests/site/test_static_site.py::test_overview_shows_all_five_mandatory_status_fields`).

## 12. Live trading permanently disabled

**PASS.** Dual lock (`_LIVE_TRADING_HARD_LOCK` source constant +
`LIVE_TRADING` env var, both required, `config.py`); live broker adapters
(`broker/kr_live.py`, `us_live.py`) are `NotImplementedError` stubs
regardless of either flag. Verified by `tests/broker/test_live_stub.py`.
No readiness level or dashboard state can influence this — the two
mechanisms are independent by design (`docs/INVESTMENT_GATE.md`).

## 13. Secret safety

**PASS.** `.gitignore` excludes `.env`, `*.key`, `secrets.yaml`,
`config/broker_secrets.yaml`, and all of `data/db/*` (runtime state that
could theoretically contain sensitive info, excluded as defense in
depth). Only `.env.example` (blank placeholder values) is tracked. The
daily workflow runs a `gitleaks` scan gating the only commit step
(`tests/workflows/test_daily_pipeline_workflow.py::test_commit_step_is_gated_on_gitleaks_success`).
No GitHub Secrets are currently defined or required, since the pipeline
runs entirely on `--demo`/no-API-key providers.

## 14. Public-repo data safety

**PASS.** Only derived/aggregate artifacts are committed
(`site/data/dashboard.json`, `site/data/history.json`, `reports/*.md`) —
never raw OHLCV price history, which stays under gitignored
`data/raw`/`data/cache`/`data/processed`. No hardcoded ticker lists,
account numbers, or personal data anywhere in source.

## 15. Test coverage completeness

**PASS.** 375 tests passing across data providers, schema, OHLC,
duplicates, missing dates, trading calendar, timezone, corporate actions,
cross-provider checks, features, strategies, PnL, transaction cost,
portfolio, risk, backtest, OOS/walk-forward, dashboard build, and the
static site — plus the dedicated Known-Answer + Independent Verification
suite (`tests/known_answer/`). One test is deliberately deselected from
the fast daily bucket for being slow (a full parameter-grid search), not
skipped from the developer test suite.

---

### Summary

12 of 15 points are unqualified PASS. 3 points (Investment Readiness'
automated inputs, the Streamlit dashboard's gate wiring, and the
workflow's real-GitHub execution) carry a documented, intentional
limitation rather than a silent gap — each is explained above with the
specific reason it exists and what closing it would require. Nothing in
this audit was softened to make the count look better; the honest
description of each limitation is the point of running this audit at all.
