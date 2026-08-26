# Security

This document covers secret handling, the live-trading safety lock, and
what is and isn't safe to keep in this (potentially public) repository.

## Live trading is permanently disabled by default

Two independent locks both have to be open before any live order could
ever be placed, and one of them requires editing source code:

1. `src/quant/config.py::_LIVE_TRADING_HARD_LOCK = False` — a Python
   constant, not read from any config file or environment variable. A
   human has to edit this line of source code to change it.
2. The `LIVE_TRADING` environment variable must also be `"true"`.

`is_live_trading_enabled()` returns `_LIVE_TRADING_HARD_LOCK and env_flag`
— with lock #1 always `False` as shipped, the function always returns
`False` regardless of `.env` contents, `config/*.yaml`, or anything the
Investment Readiness Gate computes (see `docs/INVESTMENT_GATE.md` — the
two mechanisms are entirely independent).

`src/quant/broker/kr_live.py` and `us_live.py` are interface-only stubs:
every order-placing method raises `NotImplementedError` unconditionally,
regardless of the flags above. There is currently no code path in this
repository — none, at any readiness level — that can place a real
brokerage order. Enabling real order execution, or removing either lock,
is explicitly called out in the governing project spec as one of the few
actions that require the user's direct, explicit approval; it is never
done automatically, and this document is not an instruction to do it.

## Secrets: what must never be committed

`.gitignore` excludes, and the daily GitHub Actions workflow scans for:

- `.env` (real credentials) — only `.env.example` (all blank/placeholder
  values) is tracked.
- `*.key`, `secrets.yaml`, `config/broker_secrets.yaml`.
- Anything under `data/db/*` except `.gitkeep` — this is local runtime
  state (`VersionStore`, `AuditLog`, paper-broker equity/position state,
  the Research DB sqlite file), not something that belongs in git
  history, and not something that should ever contain a credential in the
  first place, but excluded regardless as defense in depth.
- Anything under `data/raw/*`, `data/processed/*`, `data/cache/*`, `logs/*`
  except `.gitkeep`.

`.env.example` documents the only credential-shaped variables this
project currently defines — `KIS_APP_KEY`/`KIS_APP_SECRET`/
`KIS_ACCOUNT_NO` (Korea broker, future use) and
`ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (US broker, future use) — and none of
them are required by anything the research pipeline actually runs today
(`run_research.py`, `run_scan.py`, `run_backtest.py`, `generate_report.py`,
`generate_dashboard_data.py` all use `--demo` synthetic data or the
no-API-key `pykrx`/`yfinance` providers). If a real brokerage integration
is ever built behind `broker/kr_live.py` / `us_live.py`, its credentials
belong in `.env` locally and in **GitHub Secrets** (repository or
environment secrets, never a workflow file, never a committed config
file) for CI — at the time of writing, this repository defines no GitHub
Secrets because nothing in the automated pipeline needs one.

**Deleting a GitHub Secret, exposing sensitive info, or downgrading any
security control** are, per the governing project spec, actions that
require the user's direct, explicit approval before being done — never
performed automatically by an agent working on this codebase.

## Pre-push checks (CI defense in depth)

`.github/workflows/daily-pipeline.yml`'s `research` job runs a `gitleaks`
secret scan (`gitleaks/gitleaks-action@v2`) immediately before the only
step that commits anything back to the repository
(`site/data/dashboard.json`, `site/data/history.json`, `reports/*.md`).
The commit step is conditioned on `steps.gitleaks.outcome == 'success'`
— if the scan itself fails to run cleanly (not just "found a secret", but
also any scan-tool error), the workflow explicitly refuses to auto-commit
rather than assuming a clean scan (`tests/workflows/test_daily_pipeline_workflow.py`
pins this behavior structurally). A human setting up this repository for
real should still run a one-time manual secret scan and check for large
files before the very first push, since the very first push carries the
full history that follows it.

## Public-repo data policy

This project is designed to be safe to keep in a **public** GitHub
repository, because of what it deliberately does *not* commit:

- **No raw price/OHLCV data is ever committed.** `data/raw`, `data/cache`,
  and `data/processed` are all gitignored. Only small, derived, aggregate
  artifacts are committed: `site/data/dashboard.json` (a single day's
  snapshot of scores, statuses, and top-N candidate summaries — not a
  price history table), `site/data/history.json` (compact per-day trend
  rows: scores and statuses, never raw prices), and `reports/*.md` (a
  human-readable Markdown summary).
- Whether a given data provider's output may be redistributed at all is
  the provider's own terms, not this project's to decide — this project
  avoids the question by never redistributing raw provider data in the
  first place, committing only the aggregated results of analysis
  performed on it locally/in CI.
- No hardcoded ticker lists, account numbers, or personal information
  appear anywhere in source.

## Reporting a problem

If you find a credential, private key, or other secret that was
accidentally committed to this repository's history, treat it as
compromised immediately (rotate/revoke it at the source, e.g. the broker
or data-vendor dashboard) — removing it from a later commit does not
remove it from git history by itself, and rewriting published history is
a separate, disruptive operation that should not be done without
understanding that tradeoff first.
