"""The run has to be legible without opening a log.

On 2026-09-30 the daily job ran for 55 minutes, fetched real US market data
for 42 of them, and refused to publish the result. Whether that refusal was
correct was decided by one `publishability` block and explained by a handful
of reason strings -- all of them somewhere in the middle of a log GitHub
renders only the first hundred lines of. From the outside the run looked
exactly like the three and a half weeks of runs that had done nothing at all.

So the summary is not decoration. These tests pin the two things that make
it worth having: it says plainly when nothing was published and why, and it
never becomes a way for the run to fail.
"""
from __future__ import annotations

import json

import pytest

from quant.dashboard_export.run_summary import render_run_summary, write_job_summary


def _payload(publishable: bool, **over):
    data = {
        "schema_version": 2,
        "as_of": "2026-09-29",
        "data_source_mode": "real" if publishable else "synthetic",
        "publishability": {
            "data_source_mode": "real" if publishable else "synthetic",
            "publishable": publishable,
            "reasons": [] if publishable else ["korea: 데이터 소스 접근 실패", "us: 합성 데이터"],
            "markets": {
                "korea": {"state": "STALE", "gap_sessions": 3},
                "us": {"state": "FRESH", "gap_sessions": 0},
            },
        },
        "overview": {
            "data_integrity": "PASS" if publishable else "FAIL",
            "mandatory_validation_pass_rate": 100.0 if publishable else 0.0,
            "pipeline_health": "PASS" if publishable else "FAIL",
            "investment_readiness": "DATA_VERIFIED" if publishable else "DATA_INVALID",
        },
        "markets": {
            "korea": {"status": "DATA UNAVAILABLE", "blocked": True,
                      "block_reason": "korea 시장 데이터를 가져오지 못했습니다", "universe_size": 0,
                      "candidates": []},
            "us": {"status": "OK", "blocked": False, "block_reason": None,
                   "universe_size": 400, "candidates": [{"symbol": "AAPL"}]},
        },
    }
    data.update(over)
    return data


def test_a_refusal_to_publish_is_stated_outright():
    md = render_run_summary(_payload(False))
    assert "게시 불가" in md
    assert "dashboard.json" in md, "must say the file was not updated, not merely that something failed"


def test_every_reason_for_refusing_appears():
    """A verdict without its reasons sends the reader back into the log,
    which is the problem this exists to solve."""
    md = render_run_summary(_payload(False))
    assert "데이터 소스 접근 실패" in md
    assert "합성 데이터" in md


def test_a_publishable_run_does_not_claim_it_withheld_anything():
    md = render_run_summary(_payload(True))
    assert "게시 가능" in md
    assert "게시하지 않은 이유" not in md


def test_each_market_is_reported_separately():
    """One market failing while the other worked is the normal case now;
    a single overall verdict would hide the half that succeeded."""
    md = render_run_summary(_payload(False))
    assert "korea" in md and "us" in md
    assert "DATA UNAVAILABLE" in md
    assert "400" in md, "the working market's universe size should still be visible"


def test_reason_text_cannot_break_the_table():
    """Markdown tables end a cell at `|` and a row at a newline, so a reason
    string containing either would silently mangle every row after it."""
    data = _payload(False)
    data["markets"]["korea"]["block_reason"] = "pipe | inside\nand a newline"
    md = render_run_summary(data)
    row = [ln for ln in md.splitlines() if "korea" in ln and ln.startswith("|")][0]
    assert row.count("|") == 5, f"row gained or lost cells: {row!r}"


def test_a_very_long_reason_is_truncated_rather_than_wrapped():
    data = _payload(False)
    data["markets"]["korea"]["block_reason"] = "x" * 2000
    md = render_run_summary(data)
    row = [ln for ln in md.splitlines() if ln.startswith("| ⛔ korea")][0]
    assert len(row) < 400


def test_the_disclaimer_survives_into_the_summary():
    """The spec requires the meaning of 'passed validation' to travel with
    the claim, wherever the claim is shown."""
    md = render_run_summary(_payload(True))
    assert "손실이 없다는 뜻도 아닙니다" in md


def test_missing_sections_do_not_raise():
    """A crashed run produces a partial payload. The summary is the thing
    that has to explain that, so it cannot be the thing that dies on it."""
    for partial in ({}, {"publishability": {}}, {"markets": {"korea": None}},
                    {"overview": None, "markets": {}}):
        md = render_run_summary(partial)
        assert isinstance(md, str) and md.strip()


def test_write_job_summary_appends_to_the_given_file(tmp_path):
    target = tmp_path / "summary.md"
    target.write_text("earlier content\n", encoding="utf-8")
    assert write_job_summary(_payload(True), target) is True
    text = target.read_text(encoding="utf-8")
    assert text.startswith("earlier content")
    assert "게시 가능" in text


def test_write_job_summary_is_a_no_op_outside_ci(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert write_job_summary(_payload(True)) is False


def test_reporting_never_fails_the_run_it_reports_on(tmp_path):
    """If the summary file cannot be written, that is a reporting problem,
    not a reason to lose an hour of research."""
    unwritable = tmp_path / "no-such-dir" / "summary.md"
    assert write_job_summary(_payload(True), unwritable) is False


def test_summary_is_rendered_from_the_payload_not_a_second_opinion():
    """The gate acts on `publishability.publishable`; the summary must read
    that same field, or the two can disagree about the same run."""
    data = _payload(True)
    data["publishability"]["publishable"] = False
    md = render_run_summary(data)
    assert "게시 불가" in md, "the summary followed something other than the gate's own verdict"
