# Architecture

## 0. 가장 중요한 절대 원칙 (the one absolute principle)

This platform's top priority, in strict order, is: (1) data accuracy, (2)
data integrity, (3) calculation accuracy, (4) backtest reliability, (5)
reproducibility, (6) overfitting prevention, (7) verifiability, (8)
long-term pre-live verification, (9) Fail-Closed architecture, (10)
full GitHub-based automation. **High returns are explicitly not on this
list, and nothing in this codebase should be changed in a way that trades
one of the above away for a better-looking return number.**

Two numbers that must never be confused with each other, anywhere in this
codebase, in a report, or on the dashboard:

- **Data Validation 100%** — a binary statement about whether every
  mandatory data-quality check passed. It has no partial-credit state
  (`mandatory_validation_pass_rate` is always exactly 0.0 or 100.0) and no
  bearing on whether any strategy will be profitable.
- **Investment Prediction Accuracy** — anything about whether a strategy,
  ranking, or forecast will be right about the future. This is never
  100%, is never claimed to be, and this platform never asserts that any
  return is guaranteed or that loss is impossible (see "Forbidden
  phrases" below).

See `docs/DATA_VALIDATION.md` for the full detail on the first, and
`docs/INVESTMENT_GATE.md` for how the second is deliberately kept
conservative rather than inflated.

**Fail-Closed**: if a market's mandatory data-quality checks fail for a
given day, that market's candidate/strategy generation is halted for that
day — "no investment decision when data errors exist." This never blocks
the dashboard itself from deploying; a blocked day is rendered clearly as
a failure, not hidden by a stale or missing dashboard. See
`docs/DATA_VALIDATION.md`.

## Design goal

This is **not** an auto-trading bot. It is a research pipeline whose job is to
answer, every day, "which strategies and which names are currently the most
promising candidates, and how much should I trust that judgment" — and to
prefer answers that are *reproducible and likely to survive out-of-sample*
over answers that simply maximize a backtested return number.

## Pipeline (also see `src/quant/pipeline/research_pipeline.py`)

```
Market Data (data/)
  -> Universe Engine (universe/)
  -> Data Quality Engine (quality/) ---- Fail-Closed gate (quality/gate.py,
  |                                      quality/pipeline_gate.py) --
  |                                      BLOCKED markets stop here; nothing
  |                                      below this line runs for them today.
  v (only on PASS, using the resulting canonical OHLCV + universe snapshot)
  -> Feature Engine (features/)
  -> Market Regime Detection (regime/)
  -> Market Screening (scanner/)
  -> Strategy Library (strategy/)
  -> Backtesting (backtest/)
  -> Performance Analytics (analytics/)
  -> Train/Validation/OOS + Walk-Forward (validation/)
  -> Strategy Ranking + Overfitting + Monte Carlo (ranking/)
  -> Portfolio Construction (portfolio/)
  -> Risk Analysis (risk/)
  -> Research Database (research_db/) -- every experiment persisted here
  -> Daily Research Report (report/) -- renders a distinct block-banner for
  |                                     a Fail-Closed day, never conflated
  |                                     with "no candidates found"
  -> Investment Readiness Gate (quality/readiness.py) -- 7-level ladder,
  |                                     never exceeds ELIGIBLE_FOR_MANUAL_REVIEW
  -> Dashboard Data Export (dashboard_export/) -> site/data/*.json
  -> Static Dashboard (site/) -> GitHub Pages, via GitHub Actions
  -> Paper Trading (broker/) -- simulated only, >= 250 real sessions
  |                             required before PAPER_VERIFIED
  -> [future] Live Trading (broker/*_live.py, disabled by construction --
                             see docs/SECURITY.md)
```

`run_research.py` runs this whole chain end to end for both markets, going
through the Fail-Closed gate via
`quant.pipeline.research_pipeline.run_market_research()`. Every other
daily-candidate-generating entry point (`run_scan.py`, `run_paper.py`,
`run_backtest.py`, `generate_report.py`) goes through the same gate via
`quant.quality.pipeline_gate.run_gated_scan()` — there is exactly one
choke point for "is today's data good enough to act on," not one per
script. See `docs/DATA_VALIDATION.md` for the full detail.

## Package layout

```
src/quant/
  config.py          # loads config/*.yaml, env vars, hardcodes LIVE_TRADING=False
  data/               # MarketDataProvider interface + KR (pykrx) / US (yfinance) impls
                      # + secondary (finance-datareader / Stooq) providers for
                      # cross_source checks + local parquet/sqlite cache (store.py)
  quality/            # Data Quality Engine (schema/ohlc/completeness/corporate_actions/
                      # cross_source/canonical/audit), the Fail-Closed gate (gate.py),
                      # the single entry point every caller uses (pipeline_gate.py),
                      # the Investment Readiness ladder (readiness.py), and the shared
                      # CLI/dashboard health computation (system_status.py)
  universe/           # Universe construction rules per market, config-driven
  features/           # Price/Trend/Momentum/Volatility/Volume/MeanReversion/Fundamental
  regime/             # Bull/Bear/Sideways/HighVol/LowVol/RiskOn/RiskOff classifier
  scanner/            # Screening filters + daily candidate scanner with reasons
  strategy/           # BaseStrategy interface + concrete strategy modules
  backtest/           # Event-driven-ish vectorized backtester with realistic costs
  analytics/          # Performance metrics, benchmark comparison, plots
  validation/         # IS/Validation/OOS split, walk-forward analysis, param stability
  ranking/            # Composite Quant Strategy Score, overfitting detection, Monte Carlo
  portfolio/          # Weighting schemes + constraints
  risk/               # Pre-trade Risk Manager (position/exposure/drawdown/vol limits)
  research_db/        # SQLite experiment database (reproducibility metadata)
  report/             # Daily research report generator (Markdown + HTML)
  dashboard_export/   # Builds site/data/dashboard.json + history.json from a full
                      # pipeline run + SystemStatus; enforces the forbidden-phrase guard
  broker/             # BrokerInterface + KoreaPaperBroker/USPaperBroker (+ live stubs)
  pipeline/           # Orchestrates the full chain, Fail-Closed-aware end to end
  utils/              # logging, trading calendar, misc helpers

site/                 # Static GitHub Pages dashboard (single self-contained index.html
                      # + data/dashboard.json + data/history.json), zero external deps
.github/workflows/     # daily-pipeline.yml: 07:00 KST primary + 07:15 KST idempotent
                      # recovery run + workflow_dispatch, Fail-Closed-aware, dashboard
                      # always attempts to deploy regardless of upstream failures
docs/                  # DATA_VALIDATION.md, INVESTMENT_GATE.md, SECURITY.md (this file
                      # stays at the repo root so README.md's existing link keeps working)
```

`tests/` mirrors this layout one-to-one (`tests/quality/`, `tests/dashboard_export/`,
`tests/site/`, `tests/workflows/`, `tests/known_answer/`, etc.).

## Investment Readiness Gate

A strict, one-way, 7-level ladder
(`DATA_INVALID -> DATA_VERIFIED -> RESEARCH_VALIDATED -> OOS_VALIDATED ->
PAPER_TRADING -> PAPER_VERIFIED -> ELIGIBLE_FOR_MANUAL_REVIEW`) computed by
`quant.quality.readiness.assess_readiness()`. Nothing in this codebase can
report a level past `ELIGIBLE_FOR_MANUAL_REVIEW`, and that level means
"ready for a human to review," never "ready to trade automatically." Full
detail, including why the ladder is conservative by construction, is in
`docs/INVESTMENT_GATE.md`.

## Daily automation & static dashboard

The daily pipeline runs entirely on GitHub Actions
(`.github/workflows/daily-pipeline.yml`), writing its output to a static
site (`site/`) served by GitHub Pages — no paid backend, no server to run.
`quant.dashboard_export.export.build_dashboard_data()` assembles one JSON
snapshot per day plus a compact trend history; `site/index.html` is a
single self-contained page (inline CSS/JS, no CDN, relative `fetch()`
only) that renders it. See `docs/DATA_VALIDATION.md` and
`docs/INVESTMENT_GATE.md` for what the dashboard is required to show (and
forbidden from ever claiming).

## Data source defaults (no API key required)

- **Korea**: [`pykrx`](https://github.com/sharebook-kr/pykrx) scrapes KRX's
  public data endpoints for OHLCV, market cap, and fundamental
  (PER/PBR/EPS/dividend yield) tables for KOSPI/KOSDAQ, plus ETF price data.
- **US**: [`yfinance`](https://github.com/ranaroussi/yfinance) for OHLCV,
  corporate actions (splits/dividends) and basic fundamentals. Universe
  constituents (S&P 500 / NASDAQ-100) are fetched dynamically from public
  reference tables (e.g. Wikipedia) at run time and cached locally — **no
  ticker list is hardcoded in source code.** A broader "all listed" universe
  can be layered on later via an exchange listing endpoint.

Both providers sit behind a `MarketDataProvider` abstract interface
(`src/quant/data/base.py`), so a paid data vendor can be swapped in later
without touching anything downstream.

> **Sandbox network note:** the cloud workspace this was built in only has
> egress to package registries (pypi), not to KRX/Yahoo/Wikipedia. The data
> layer is fully implemented and unit-tested against synthetic fixtures, but
> live fetches must be exercised from an environment with normal internet
> access (your own machine, a VPS, or a connected desktop folder). See
> `README.md` -> "Running with real data".

## Reproducibility

Every backtest run persisted to the Research DB stores: code version (git
commit hash if available), a dataset version hash, the exact parameter set,
the universe definition, the date range, transaction cost assumptions, and
all computed metrics — so any past result can be located and re-run.

## Safety

`LIVE_TRADING` is `False` both in `.env.example` and hardcoded as a default
in `src/quant/config.py`. `src/quant/broker/kr_live.py` and `us_live.py` are
interface-only stubs that raise `NotImplementedError` on every order method.
No code path in this repository can place a real order. Full detail
(the dual-lock mechanism, secret handling, CI secret scanning, public-repo
data policy) is in `docs/SECURITY.md`.

## Further reading

- `docs/DATA_VALIDATION.md` — the Data Quality Engine, its mandatory
  checks, the two-tier metric separation, and Known-Answer/Independent
  Verification testing.
- `docs/INVESTMENT_GATE.md` — the 7-level Investment Readiness ladder and
  the required, never-conflated dashboard fields.
- `docs/SECURITY.md` — secrets, the live-trading lock, CI secret
  scanning, and what is/isn't safe to commit to a public repo.
- `FINAL_AUDIT.md` — the project's own 15-point self-audit against the
  governing specification.
