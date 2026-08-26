# Quant Research & Trading Platform

A personal daily research pipeline for Korean (KOSPI/KOSDAQ, KR-listed ETFs)
and US (NYSE/NASDAQ/AMEX, US-listed ETFs) equity markets.

This is **not** an auto-trading bot. It exists to answer one question every
day: *which strategies and which names currently deserve attention, and how
much should that judgment be trusted?* It is built to prefer a strategy that
is reproducible and likely to survive out-of-sample over one that simply
posted the highest backtested return. See `ARCHITECTURE.md` for the full
pipeline diagram and package layout.

No cryptocurrency support. No hardcoded ticker lists anywhere — universes
are built dynamically from each market's own listing/index data.

**Priority order, in this exact sequence, is: data accuracy, data
integrity, calculation accuracy, backtest reliability, reproducibility,
overfitting prevention, verifiability, long-term pre-live verification,
Fail-Closed architecture, and only then automation.** High returns are
deliberately not on that list. See `ARCHITECTURE.md` section 0 and
`docs/DATA_VALIDATION.md` / `docs/INVESTMENT_GATE.md` for what that means
in practice.

## Fail-Closed: a bad data day stops candidate generation, not the dashboard

Every daily-candidate-generating entry point (`run_scan.py`,
`run_paper.py`, `run_backtest.py`, `generate_report.py`, `run_research.py`)
runs today's data through the Data Quality Engine first
(`quant.quality.pipeline_gate.run_gated_scan()` /
`run_market_research()`). If even one mandatory check fails for a market,
no candidates, no strategy evaluation, and no paper-trading order are
generated for that market that day — "no investment decision when data
errors exist." **This never blocks the dashboard from deploying**: a
blocked day is rendered as a clear, distinct failure, not hidden behind a
stale or missing site. Full detail: `docs/DATA_VALIDATION.md`.

## Investment Readiness: a 7-level ladder that never reaches "trade"

`DATA_INVALID -> DATA_VERIFIED -> RESEARCH_VALIDATED -> OOS_VALIDATED ->
PAPER_TRADING -> PAPER_VERIFIED -> ELIGIBLE_FOR_MANUAL_REVIEW`. The
highest level this system can ever compute means "ready for a human to
review" — never "ready to trade automatically," and reaching it requires
250+ real (never backfilled) paper-trading sessions among other gates.
Full detail: `docs/INVESTMENT_GATE.md`.

## Safety: live trading is off by default, at every layer

- `src/quant/config.py` hardcodes `_LIVE_TRADING_HARD_LOCK = False`. Setting
  the `LIVE_TRADING=true` environment variable does **nothing** by itself —
  the source-level lock also has to be edited, which is a deliberate code
  change, not a config toggle.
- `src/quant/broker/kr_live.py` and `us_live.py` are interface-only stubs:
  every method raises `NotImplementedError` unconditionally.
- Nothing in this repository can place a real brokerage order. Paper
  trading (`run_paper.py`, the dashboard's Paper Trading page) is fully
  simulated and persists its state to a local JSON file only.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run the test suite (should be all green before you rely on anything here):

```bash
pytest tests/ -q
```

One test (`tests/validation/test_walk_forward.py::test_walk_forward_with_param_search_picks_stable_params`)
runs a full parameter-grid Walk-Forward search and takes ~3 minutes; it is
correct but slow, so day-to-day you may want:

```bash
pytest tests/ -q --deselect tests/validation/test_walk_forward.py::test_walk_forward_with_param_search_picks_stable_params
```

## The one command

```bash
python run_research.py
```

Runs the entire pipeline end to end for both markets: market data update →
universe generation → feature computation → market regime detection →
stock screening → strategy evaluation (Walk-Forward Analysis across every
enabled strategy) → strategy ranking → candidate ranking → portfolio
construction → risk analysis → a Markdown research report written under
`reports/`. Typically takes a few minutes per market on the synthetic demo
data this environment ships with (see "Running with real data" below).

Useful flags: `--markets korea` (single market), `--param-search` (a much
slower full parameter-grid search per strategy, off by default), `--as-of
YYYY-MM-DD`, `--top-n`.

## Other CLI entry points

- `python run_scan.py --market korea [--top-n 20]` — just the Daily Market
  Scanner: universe → features → regime → screening → a ranked candidate
  report to stdout. Read-only, no side effects.
- `python run_backtest.py --strategy ma_crossover --market korea [--param-search] [--save]` —
  Walk-Forward Analysis for one strategy, fold-by-fold IS/OOS metrics, an
  Overfitting Detection assessment, and (with `--save`) a Research DB
  experiment record.
- `python generate_report.py [--as-of YYYY-MM-DD]` — regenerates the Daily
  Research Report from the latest scan + whatever strategy rankings are
  already on record, without re-running Walk-Forward Analysis.
- `python run_dashboard.py` — launches the Streamlit dashboard
  (Home / Market Scanner / Strategies / Experiments / Portfolio / Risk /
  Paper Trading tabs).
- `python run_paper.py --market korea [--top-n 10]` — one daily paper
  trading rebalance cycle: scan → constrained portfolio construction →
  orders submitted through the shared Risk Manager → equity mark recorded.
  Skips recording the day's equity mark entirely if the market is
  Fail-Closed blocked — a blocked day never silently counts as one of the
  250 required paper-trading sessions.
- `python validate_data.py --market both [--as-of YYYY-MM-DD]` — runs only
  the Data Quality Engine and prints a PASS/FAIL table per mandatory
  check, exit code 0/1. Useful to check today's data without running the
  full pipeline.
- `python validate_system.py [--skip-tests]` — the same DATA QUALITY /
  UNIT TESTS / INTEGRATION TESTS / REGRESSION TESTS / PIPELINE /
  INVESTMENT READINESS verdict the dashboard shows, as a CLI, via the
  single shared `quant.quality.system_status.compute_system_status()`
  (so the CLI and the dashboard can never disagree about system health).
- `python generate_dashboard_data.py [--as-of YYYY-MM-DD] [--skip-tests]` —
  runs the full pipeline plus system-status computation and writes
  `site/data/dashboard.json` + `site/data/history.json`, the static
  dashboard's only inputs.

Every script defaults to `--demo` (synthetic offline data) and accepts
`--as-of` to replay a specific date.

## Daily automation & the static dashboard

`.github/workflows/daily.yml` runs the whole pipeline
automatically at 07:00 KST every day, with an idempotent 07:15 KST
recovery run (skipped if 07:00 already produced today's data) and a
manual `workflow_dispatch` trigger. Every pipeline step runs with
`continue-on-error: true` and the dashboard-deploy job runs `if: always()`
— **a research/data failure is never a dashboard-deploy failure**; the
GitHub Actions run still shows red for visibility, but the public site
always reflects the latest attempt, including a clear failure state.

The dashboard itself (`site/index.html`) is a single self-contained static
page — no build step, no external scripts/CDNs, no server — served by
GitHub Pages directly from this repo. It reads only
`site/data/dashboard.json` and `site/data/history.json`, both committed by
the workflow after a `gitleaks` secret scan gates the commit step. See
`docs/DATA_VALIDATION.md` and `docs/INVESTMENT_GATE.md` for what it shows
and is forbidden from ever claiming.

### Connecting this repo to GitHub / Pages (manual, one-time)

This project was developed in a sandboxed environment with no working
GitHub authentication, so repo creation, the first push, and Pages
activation are steps you do yourself once:

1. Create a new (public or private) GitHub repository, then add it as
   this local repo's remote and push: `git remote add origin <url> && git
   push -u origin master` (or `main`, matching your default branch).
2. Before that first push, run a manual secret scan
   (`gitleaks detect --source .` or equivalent) and skim `git log
   --stat` for anything unexpectedly large — the workflow's own gitleaks
   step only protects pushes *after* this one.
3. In the repo's **Settings → Pages**, set **Source** to **GitHub
   Actions** (not "Deploy from a branch") — `daily.yml`'s
   `deploy-pages` job expects to own the deployment.
4. In **Settings → Actions → General → Workflow permissions**, ensure
   "Read and write permissions" is available to workflows (the workflow
   itself only requests `contents: write` on the one job that needs it,
   per least-privilege, but the repo-level setting must allow it).
5. No GitHub Secrets are required for the pipeline as shipped (it runs
   entirely on `--demo`/no-API-key providers). If you later wire in a
   real broker credential behind the (currently stub) live-broker
   interface, add it as a GitHub Secret, never a committed file — see
   `docs/SECURITY.md`.
6. Trigger the workflow once manually (`workflow_dispatch`, or the
   Actions tab's "Run workflow" button) to confirm the first Pages
   deployment succeeds, rather than waiting for the next 07:00 KST run.

## Configuration

All tunables live in `config/*.yaml` — no code changes needed to adjust
universe filters, cost assumptions, risk limits, ranking weights, regime
thresholds, validation split sizes, portfolio constraints, or which
strategies are enabled and their parameter grids:

| File | Controls |
|---|---|
| `settings.yaml` | markets, paths, logging, trading calendar |
| `universe_kr.yaml` / `universe_us.yaml` | universe construction filters |
| `costs.yaml` | commission/tax/slippage assumptions per market |
| `risk.yaml` | position/sector/market caps, drawdown & loss stops |
| `ranking.yaml` | Quant Strategy Score weights, overfitting thresholds |
| `regime.yaml` | bull/bear/sideways and vol-regime classification |
| `validation.yaml` | walk-forward fold sizing, parameter stability bands |
| `portfolio.yaml` | weighting scheme, constraints |
| `strategies.yaml` | which strategies are enabled + their parameter grids |
| `quality.yaml` | Data Quality Engine mandatory checks + thresholds (see `docs/DATA_VALIDATION.md`) |

## Running with real data

This project was built in a sandboxed cloud environment whose network
egress only reaches package registries (pypi) — not KRX, Yahoo Finance, or
Wikipedia. Every component was therefore developed and fully tested against
a deterministic synthetic data provider (`--demo`, the default everywhere),
which is realistic enough to exercise the whole pipeline end to end but is
**not calibrated to realistic market statistics** — don't read anything
into a demo-mode Sharpe ratio or CAGR beyond "the plumbing works."

The real providers could not be exercised against live endpoints from that
sandbox, so their first real contact is a CI run:

- **Korea**: `src/quant/data/kr_provider.py`, via `pykrx` (public KRX data,
  no API key).
- **US**: `src/quant/data/us_provider.py`, via `yfinance` (no API key). US
  universe constituents (S&P 500 / NASDAQ-100) are discovered dynamically
  from public reference tables at run time — nothing is hardcoded.

Pass **`--real`** to any CLI script, from a machine (or CI runner) with
normal internet access, to use live market data instead:

```bash
python run_scan.py --market korea --real
python generate_dashboard_data.py --real --as-of 2026-08-26
```

The daily GitHub Actions workflow passes `--real` on every data-touching
step, so the published dashboard reflects live KRX / Yahoo Finance data.
`--demo` remains the default for local runs so a stray command never
hammers a provider by accident.

> **Historical note, because it cost a day to find:** `--demo` was
> originally declared as `action="store_true", default=True` on every
> entry point, which meant `args.demo` was `True` no matter what was typed
> — there was *no* spelling of the command line that selected real data.
> The daily pipeline therefore ran on synthetic randomly-generated prices
> while producing a dashboard indistinguishable from a real one.
> `tests/cli/test_real_data_flag.py` exists to make sure that specific
> class of bug fails a test rather than a morning.

Two things worth knowing about real-data runs:

- **Request shape matters more than symbol count.** `pykrx` exposes OHLCV
  both per-symbol-all-dates and per-date-all-symbols; the Korean provider
  picks whichever axis needs fewer requests for the window asked for
  (`tests/data/test_kr_provider_bulk.py`). Building the universe over
  ~2,700 listed names is ~30 requests instead of ~2,700. The US provider
  chunks `yfinance` batch downloads so one bad chunk cannot empty the
  whole universe.
- **The universe is capped.** `filters.max_universe_size` in
  `config/universe_kr.yaml` / `universe_us.yaml` keeps the most liquid N
  names that pass every filter (400 by default), because everything
  downstream scales with universe size. Capped names stay in the snapshot
  marked excluded with a reason — nothing is silently dropped. Set it to
  `0` to disable.

If you hit a provider-specific bug (rate limiting, a schema change
upstream, a timezone edge case), it will be in `data/kr_provider.py` or
`data/us_provider.py` — the rest of the pipeline is provider-agnostic and
already validated against the same `MarketDataProvider` interface.

## Reproducibility

Every strategy evaluation persisted to the Research DB
(`data/db/research.sqlite`) stores the git commit hash, a dataset
fingerprint, the exact parameters used, the universe description, the date
range, the cost assumptions, and every computed metric — so any past result
can be located and its conditions inspected later. See
`src/quant/research_db/models.py`.

## Extending this platform

A few things are deliberately left as documented extension points rather
than over-built for a personal tool: `dataset_version_tag` fingerprints
*which* data was requested, not a content hash of the actual price data;
the overfitting detector's Probability-of-Backtest-Overfitting is a
simplified proxy, not the full combinatorially-symmetric cross-validation
procedure; portfolio "risk parity" is the common simplified/naive variant
(no cross-asset correlation); and live broker integration is an
interface-only stub (`broker/kr_live.py`, `broker/us_live.py`) waiting for a
real brokerage adapter to be written behind the same `BrokerInterface`.
Each of these is called out in its module's docstring.

## Further documentation

- `ARCHITECTURE.md` — full pipeline diagram, package layout, the one
  absolute principle this project is built around.
- `docs/DATA_VALIDATION.md` — the Data Quality Engine, Fail-Closed, and
  Known-Answer/Independent Verification testing.
- `docs/INVESTMENT_GATE.md` — the 7-level Investment Readiness ladder.
- `docs/SECURITY.md` — secrets, the live-trading lock, and the public-repo
  data policy.
- `FINAL_AUDIT.md` — the project's own 15-point self-audit.

## Disclaimer

This is a personal research tool. Its output (scans, rankings, reports,
paper trading fills) is not investment advice and is never automatically
connected to a real brokerage order. All investment decisions and their
consequences are the user's own responsibility.

Data Validation 100% means all mandatory data-quality checks passed. It
does not mean that future investment returns can be predicted with 100%
accuracy or that loss is impossible.
