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

Every script defaults to `--demo` (synthetic offline data) and accepts
`--as-of` to replay a specific date.

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

## Running with real data

This project was built in a sandboxed cloud environment whose network
egress only reaches package registries (pypi) — not KRX, Yahoo Finance, or
Wikipedia. Every component was therefore developed and fully tested against
a deterministic synthetic data provider (`--demo`, the default everywhere),
which is realistic enough to exercise the whole pipeline end to end but is
**not calibrated to realistic market statistics** — don't read anything
into a demo-mode Sharpe ratio or CAGR beyond "the plumbing works."

The real providers are code-complete but have not been exercised against
live endpoints from this environment:

- **Korea**: `src/quant/data/kr_provider.py`, via `pykrx` (public KRX data,
  no API key).
- **US**: `src/quant/data/us_provider.py`, via `yfinance` (no API key). US
  universe constituents (S&P 500 / NASDAQ-100) are discovered dynamically
  from public reference tables at run time — nothing is hardcoded.

To validate against real data, run any CLI script without `--demo` from a
machine or VPS with normal internet access, e.g.:

```bash
python run_scan.py --market korea   # omit --demo once real network access is available
```

If you hit a provider-specific bug there (rate limiting, a schema change
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

## Disclaimer

This is a personal research tool. Its output (scans, rankings, reports,
paper trading fills) is not investment advice and is never automatically
connected to a real brokerage order. All investment decisions and their
consequences are the user's own responsibility.
