"""No entry point may invent today's calendar date for a missing `--as-of`.

This is the bug that took the daily run down for three and a half weeks --
twice, in two different layers.

The first fix taught the *library* (`pipeline_gate`, `research_pipeline`) to
resolve each market's latest CLOSED session via
`quant.utils.calendar.default_as_of`, and `--as-of` was dropped from the
workflow. The run still failed, because the fix stopped one layer too low:
every CLI did

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")

before calling in, so the library's `as_of or default_as_of(market)` never
saw a None and never got to run. The workflow no longer passed a date; the
scripts supplied one themselves. The failing request in CI was for Korea on
``20260930`` at 13:42 KST -- a session that had not closed.

Two properties are pinned here, both structural, because the behavioural
version needs live providers:

1. No entry point contains a `today()`-style fallback for `as_of`.
2. `default_as_of` is what fills a missing `as_of`, and it is resolved per
   market -- a single shared date cannot be right for two markets whose
   sessions close in different timezones.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Every command the daily workflow can run, plus the modules they delegate
#: the decision to.
ENTRY_POINTS = [
    "run_scan.py",
    "run_paper.py",
    "run_backtest.py",
    "run_research.py",
    "generate_report.py",
    "generate_dashboard_data.py",
    "validate_data.py",
]

RESOLVERS = [
    "src/quant/quality/pipeline_gate.py",
    "src/quant/quality/system_status.py",
    "src/quant/pipeline/research_pipeline.py",
    "src/quant/data/kr_provider.py",
]

#: Exact wall-clock calls that are legitimate because they stamp a real event
#: or implement the one authoritative market-session resolver. Every allowlist
#: entry must carry a non-empty reason; a whole-file exemption is deliberately
#: forbidden because the same file can contain both legitimate timestamps and
#: illegitimate session selection.
ALLOWED_CLOCK_CALLS = {
    ("src/quant/analytics/performance_tracker.py", "pd.Timestamp.now"): (
        "prediction generated_at is the actual record-creation timestamp"
    ),
    ("src/quant/broker/paper_base.py", "pd.Timestamp.now"): (
        "paper fill timestamps record the actual execution event, not which market session is analysed"
    ),
    ("src/quant/collectors/report_collector.py", "pd.Timestamp.now"): (
        "Yahoo aggregate consensus has no source publication timestamp; the collection instant is the earliest provable availability"
    ),
    ("src/quant/dashboard_export/export.py", "pd.Timestamp.now"): (
        "dashboard generated_at records artifact creation time"
    ),
    ("src/quant/data/fx.py", "pd.Timestamp.now"): (
        "FX retrieved_at records when the quote was collected"
    ),
    ("src/quant/pipeline/daily_pipeline.py", "pd.Timestamp.now"): (
        "actionable-signal generated_at records artifact creation time"
    ),
    ("src/quant/pipeline/research_pipeline.py", "pd.Timestamp.now"): (
        "experiment created_at records when the experiment was persisted"
    ),
    ("src/quant/quality/adapters.py", "pd.Timestamp.now"): (
        "retrieved_at is provenance for the actual data-ingestion instant"
    ),
    ("src/quant/quality/engine.py", "pd.Timestamp.now"): (
        "quality report generated_at and audit timestamps record validation events"
    ),
    ("src/quant/universe/us_constituents.py", "time.time"): (
        "wall-clock seconds are used only for cache TTL age, never to select a market session"
    ),
    ("src/quant/utils/calendar.py", "pd.Timestamp.now"): (
        "calendar.py is the authoritative market-timezone resolver used by latest_closed_session/default_as_of"
    ),
}


def _clock_call_signature(node: ast.Call) -> str | None:
    func = ast.unparse(node.func)
    if func in {
        "datetime.now", "datetime.today", "date.today",
        "pd.Timestamp.now", "pd.Timestamp.today", "time.time",
    }:
        return func
    if func in {"pd.Timestamp", "Timestamp"} and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.lower() == "today":
            return 'pd.Timestamp("today")'
    return None


def _find_clock_calls(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            sig = _clock_call_signature(node)
            if sig is not None:
                out.append((node.lineno, sig))
    return out


def _sources(paths):
    for rel in paths:
        p = ROOT / rel
        yield rel, p.read_text(encoding="utf-8"), ast.parse(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel", ENTRY_POINTS + RESOLVERS)
def test_no_entry_point_substitutes_todays_calendar_date(rel):
    """`as_of` must never default to the runner's own idea of today.

    At 07:00 Asia/Seoul "today" has no finished session for either market,
    and on a Saturday it is not a session at all -- so `freshness`
    (mandatory, ``max_lag_sessions: 0``) is handed a bar that cannot exist
    and Fail-Closed blocks the market, with the report blaming the data
    provider.
    """
    source = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        # Only a clock reading that ends up *as the session date* is a bug.
        # `created_at=pd.Timestamp.now()` on an experiment record is a real
        # wall-clock timestamp and entirely correct; flagging it would push
        # the next person to weaken this test rather than read it.
        targets = []
        if isinstance(node, ast.Assign):
            targets = [ast.unparse(t) for t in node.targets]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [ast.unparse(node.target)]
            value = node.value
        elif isinstance(node, ast.keyword) and node.arg == "as_of":
            targets = ["as_of"]
            value = node.value
        else:
            continue
        if not any("as_of" in t for t in targets):
            continue
        for sub in ast.walk(value):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in {"today", "now"}):
                offenders.append((sub.lineno, ast.unparse(sub)))
    assert not offenders, (
        f"{rel} resolves a date from the clock: {offenders}. "
        "The session to analyse must come from default_as_of(market), which "
        "drops a session that has not closed yet."
    )


@pytest.mark.parametrize("rel", ENTRY_POINTS)
def test_missing_as_of_reaches_the_resolver_as_none(rel):
    """A CLI must pass `args.as_of` through untouched, or resolve it with
    `default_as_of` itself -- never fill it in some third way."""
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert "--as-of" in source, f"{rel} lost its --as-of override"
    passes_through = "as_of=args.as_of" in source or "as_of = args.as_of\n" in source
    resolves_properly = "default_as_of(" in source
    assert passes_through or resolves_properly, (
        f"{rel} neither forwards a missing --as-of as None nor resolves it "
        "with default_as_of(); something else is deciding the date"
    )


@pytest.mark.parametrize("rel", ["src/quant/quality/pipeline_gate.py"])
def test_the_gate_itself_resolves_per_market(rel):
    """The single choke point every candidate-generating path goes through
    must resolve the market it was asked about, not a run-level date."""
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert "default_as_of(market)" in source, (
        "pipeline_gate must resolve as_of for the market it is gating -- at "
        "07:00 KST the correct Korean and US sessions are frequently "
        "different dates"
    )


def test_multi_market_clis_do_not_share_one_date_between_markets():
    """`validate_data.py` and `generate_report.py` run both markets in one
    loop. Resolving once above the loop is the shared-date mistake wearing
    a different hat."""
    for rel in ("validate_data.py", "generate_report.py"):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "as_of=args.as_of" in source, (
            f"{rel} should hand each market the raw override (usually None) "
            "so the market resolves its own session"
        )


def test_the_allowed_clock_callers_are_the_only_ones_left():
    """Any direct wall-clock read in src must be an exact, justified exception."""
    assert ALLOWED_CLOCK_CALLS
    assert all(
        isinstance(reason, str) and reason.strip()
        for reason in ALLOWED_CLOCK_CALLS.values()
    ), "every allowed clock call must include a non-empty reason"

    found = set()
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        for _, signature in _find_clock_calls(source):
            found.add((rel, signature))

    unexpected = found - set(ALLOWED_CLOCK_CALLS)
    assert not unexpected, (
        f"new clock-derived calls: {sorted(unexpected)}. Session selection "
        "must use default_as_of(market)/latest_closed_session(market); only "
        "true event timestamps or resolver internals may be allowlisted, "
        "and every exception requires a reason."
    )


@pytest.mark.parametrize(
    "snippet, expected",
    [
        ("datetime.now()", "datetime.now"),
        ("datetime.today()", "datetime.today"),
        ("date.today()", "date.today"),
        ("pd.Timestamp.now()", "pd.Timestamp.now"),
        ('pd.Timestamp("today")', 'pd.Timestamp("today")'),
        ("time.time()", "time.time"),
    ],
)
def test_clock_guard_recognizes_all_forbidden_patterns(snippet, expected):
    calls = _find_clock_calls(f"x = {snippet}\n")
    assert calls == [(1, expected)]
