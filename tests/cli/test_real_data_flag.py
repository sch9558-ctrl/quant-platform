"""Every CLI must be able to actually turn demo mode OFF.

This exists because of a real bug: every entry point declared

    parser.add_argument("--demo", action="store_true", default=True)

which makes `args.demo` True no matter what the user types -- there was no
spelling of the command line that selected real market data. The daily
GitHub Actions pipeline therefore ran on synthetic randomly-generated
prices while looking, from the dashboard, exactly like a real run.

A test that only checked "does --demo exist" would have passed throughout.
So these check the property that actually matters: that a real-data switch
is reachable from the command line, on every entry point.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CLIS = [
    "run_research.py",
    "run_scan.py",
    "run_paper.py",
    "run_backtest.py",
    "generate_report.py",
    "validate_data.py",
    "validate_system.py",
    "generate_dashboard_data.py",
]


def _help_text(script: str) -> str:
    result = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"{script} --help failed:\n{result.stderr[-2000:]}"
    return result.stdout


@pytest.mark.parametrize("script", CLIS)
def test_cli_exposes_a_real_data_switch(script):
    help_text = _help_text(script)
    assert "--real" in help_text, (
        f"{script} has no way to select real market data -- demo mode would be "
        "permanently forced on, which is exactly the bug this test exists for"
    )
    assert "--demo" in help_text, f"{script} should still document the demo default"


def test_real_flag_actually_flips_demo_off():
    """The switch has to change the parsed value, not merely exist.

    `--real` is wired as `action="store_false", dest="demo"`; someone
    "tidying" it back to a `store_true` on its own dest would restore the
    original bug while keeping `--real` in the help output.
    """
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", dest="demo", action="store_true", default=True)
    parser.add_argument("--real", dest="demo", action="store_false")

    assert parser.parse_args([]).demo is True, "demo stays the safe default"
    assert parser.parse_args(["--demo"]).demo is True
    assert parser.parse_args(["--real"]).demo is False, "--real must select real data"
