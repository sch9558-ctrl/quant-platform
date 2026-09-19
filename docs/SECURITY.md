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

`.github/workflows/daily.yml`'s `research` job runs a `gitleaks`
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

## Private dashboard hosting

The dashboard is **not** published to public GitHub Pages. It is deployed
to Cloudflare Pages behind Cloudflare Access, and the daily workflow's
`deploy` job is the only thing that publishes it.

### Why Access rather than a password gate in the page

Anything the browser can check, the browser can be told to skip. A
password compared in JavaScript, a hash embedded in the page, a
`localStorage` flag, a CSS rule that hides the content — all of these are
bypassed by opening dev tools, and none of them protect
`/data/dashboard.json`, which is the file that actually contains the
research. A viewer who never loads the HTML at all is unaffected by any
of it.

Cloudflare Access sits in front of the whole deployment at the edge, so an
unauthenticated request never reaches an origin file. The HTML and every
asset under `/data/` are gated identically; there is no "just fetch the
JSON directly" path to route around.

### Why email one-time PIN rather than a shared password

The original requirement was a shared password. Access's email allowlist
with a one-time PIN was chosen instead because it is strictly better on
the axis that matters here: **there is no password to protect.** Nothing
to hash, nothing to store in a secret manager, nothing to rotate when it
leaks, no brute-force protection to implement and get subtly wrong, and no
way for the credential to end up in a commit, a screenshot, or a browser
history. Access owns the rate limiting and the session handling.

A shared-password mode remains implementable as a Pages Function if it is
ever wanted (`AUTH_MODE=shared_password`), with the password held only in
Cloudflare's secret storage — never in the repository, the build artifact,
or any file the browser receives. That path carries the extra obligations
the PIN flow avoids, which is why it is not the default.

### Fail-closed

If the deployment credentials are missing, the `deploy` job fails and
publishes nothing. It never falls back to a public host. An
authentication problem must not be resolved by making the data public —
the failure mode of "no dashboard this morning" is recoverable, and the
failure mode of "the research is on the open internet" is not.

### What is verified before every deployment

`tools/verify_dashboard_build.py` runs against the exact directory about
to be uploaded and refuses the deployment if:

- required files are missing or unparseable;
- payload metadata is self-contradictory — most importantly a
  `DATA INTEGRITY PASS` headline over a payload whose own metadata says it
  is synthetic or stale, which is precisely the state that was live;
- a test, fixture, sample, or demo artifact leaked into the deploy
  directory;
- anything credential-shaped appears in a deployable text file. This is a
  narrow, high-signal scan over the built artifact — the one place a
  repository-wide scan can miss, because the file did not exist when that
  scan ran. It complements gitleaks rather than replacing it.

### Repository visibility

The repository is currently public. It contains research logic, strategy
parameters, and committed dashboard/validation output. If any of that is
considered sensitive, the repository should be made private — note that
GitHub Pages on a free account cannot serve a private repository, which no
longer matters now that hosting has moved off Pages.

### robots.txt is not a control

`site/robots.txt` requests that crawlers stay away. It is a courtesy to
well-behaved crawlers and nothing more: it stops no one who ignores it or
who simply knows a URL. Access is the control; robots.txt is a sign on the
door.
