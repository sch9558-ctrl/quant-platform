# Investment Readiness Gate

This document describes the Investment Readiness ladder: what each level
means, what must be true to reach it, and the hard guarantee that nothing
in this codebase can push a result past the final level. Reference:
`src/quant/quality/readiness.py`, spec sections 29-31.

## The ladder

A strict, one-way, strictly sequential ladder. Reaching level *N* requires
every condition of every level below *N* to still hold — there is no path
that skips a level, and level order is fixed:

```
DATA_INVALID
    |  mandatory data validation passes, no unresolved critical data anomaly
    v
DATA_VERIFIED
    |  unit tests + integration tests + critical pipeline tests all pass
    v
RESEARCH_VALIDATED
    |  Out-of-Sample validation passes AND Walk-Forward validation passes
    v
OOS_VALIDATED
    |  transaction-cost stress test passes AND overfitting risk acceptable
    v
PAPER_TRADING
    |  >= 250 real wall-clock paper-trading sessions completed
    v
PAPER_VERIFIED
    |  no unresolved critical software error AND a risk report was generated
    v
ELIGIBLE_FOR_MANUAL_REVIEW   <-- the final, highest level this system can ever report
```

`ELIGIBLE_FOR_MANUAL_REVIEW` means exactly what it says: **eligible for a
human to review**, not eligible to trade, not a recommendation, and never
an instruction to place an order. `assess_readiness()`
(`readiness.py`) has no branch that returns anything past this level —
there is no eighth level, and nothing else in this codebase (dashboard
export, reports, CLIs) computes or displays a readiness level through any
path other than this one function.

## Inputs are conservative by construction

`ReadinessInputs` (`readiness.py`) has no field that defaults to `True`
except the two "no unresolved critical X" flags, which represent an
absence of a known problem, not a completed verification — and even
those are explicit dataclass fields that any part of the system can set
to `False` the moment a real issue is found. Every field that represents
an actual verification (tests passing, OOS/walk-forward passing, cost
stress test, overfitting risk, paper trading sessions) defaults to
`False`/`0`. This means: **if a verification was never run, or the
system computing readiness doesn't yet know how to check it, the ladder
reports a lower level than reality might warrant — never a higher one.**
Under-reporting readiness is the safe failure mode; over-reporting it is
not.

This shows up concretely in
`quant.quality.system_status.compute_system_status()`, the function that
builds `ReadinessInputs` for the daily CLI (`validate_system.py`) and the
dashboard (`generate_dashboard_data.py`). The paper-session input is now
backed by the existing `ResearchDB`: only cycle summaries explicitly marked
`readiness_eligible=true` are counted. Raw broker equity marks alone are not
enough. The remaining strategy-validation-specific inputs
(`oos_validation_pass`, `walk_forward_pass`, `cost_stress_test_pass`,
`overfitting_risk_acceptable`, and `risk_report_generated`) are still
deliberately left at their conservative defaults until one persisted contract
can prove them without inference. As a result, the automatically computed
ladder may intentionally remain below `PAPER_TRADING` even when daily data
quality and software tests pass. This is conservative by design rather than a
silent gap.

## Paper trading: 250 validated sessions, never backfilled

The required count is configured once at
`settings.yaml -> paper_trading.required_validated_sessions` (currently 250).
A counted session means exactly **one distinct validated market session with a
successfully persisted paper NAV whose completed cycle is explicitly marked
readiness-eligible under the configured execution policy**. Raw NAV rows remain
an immutable audit trail, but they are not automatically verification days.
A no-trade day counts only when no execution was required and its validated NAV
is persisted. A Fail-Closed market day, failed NAV persistence, final-research
authorization failure, execution-policy mismatch, or replay of an already-counted
session does not add a session. Historical replay or backfill can never
manufacture elapsed pre-live time.

The production cost configuration currently specifies a one-bar delay and
`next_open` fill. The immediate caller-price PaperBroker adapter is therefore
not allowed to manufacture readiness credit for a rebalance. Until delayed
execution is represented faithfully, such sessions may record an audit NAV but
must remain readiness-ineligible. Legacy pre-audit NAV rows are preserved rather
than rewritten and are not grandfathered into the 250-session clock.

This is why `run_paper.py`, when its market is Fail-Closed blocked for the day,
skips recording that day's equity mark entirely rather than recording a
placeholder — a blocked day is not a verified paper-trading session and
must not silently count as one.

## The disclaimer

Every `ReadinessResult` carries the same fixed disclaimer text
(`readiness.DISCLAIMER`), and it is rendered on the dashboard next to
every readiness/validation status, never only in a footnote:

> "Data Validation 100% means all mandatory data-quality checks passed. It
> does not mean that future investment returns can be predicted with 100%
> accuracy or that loss is impossible."

## Live trading is a separate lock entirely

The readiness ladder and live trading are two independent mechanisms.
Reaching `ELIGIBLE_FOR_MANUAL_REVIEW` does not enable, unlock, or
influence live trading in any way — see `docs/SECURITY.md` and
`quant.config.is_live_trading_enabled()`. Live trading requires a source
code edit (`_LIVE_TRADING_HARD_LOCK` in `config.py`) in addition to an
environment variable; nothing the readiness gate computes can flip that
switch, and nothing in this system automatically executes a real order
even if both locks were somehow opened by a human.

## Required dashboard fields (never conflate these)

Per spec section 33, the dashboard's Overview must show these five fields
as distinct, separately-labeled PASS/WARNING/FAIL (or ladder-level)
indicators — never collapsed into one score, and never a bare numeric
percentage standing in for a status:

- **Data Integrity** — PASS/FAIL (from `DataQualityReport.overall_status`)
- **Mandatory Validation Pass Rate** — 100% or 0%, never partial
- **Pipeline Health** — PASS/FAIL (did the pipeline run to completion
  without crashing)
- **Strategy Validation** — PASS/WARNING/FAIL (OOS/Walk-Forward/
  overfitting verdict for the day's evaluated strategies)
- **Investment Readiness** — one of the seven ladder levels above

The static dashboard (`site/index.html`) renders exactly these five field
names in its Overview tab (`tests/site/test_static_site.py` asserts all
five are present in the HTML). The dashboard, reports, and this codebase
must never display: "100% safe", "no loss possible", "100% profit",
"100% accurate investment", "Guaranteed Return", or any equivalent
phrasing — enforced programmatically by
`quant.dashboard_export.export._assert_no_forbidden_phrases()`, which
scans the entire dashboard JSON payload for `FORBIDDEN_PHRASES` before it
is ever written to disk, and by `tests/site/test_static_site.py`'s
guardrail over the static HTML itself.
