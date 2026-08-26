#!/usr/bin/env python3
"""Launch the Streamlit research dashboard (spec section 22 / CLI section 27).

Usage:
    python run_dashboard.py [-- <extra streamlit args>]

This is a thin wrapper around `streamlit run dashboard/app.py` so the user
has one consistent command to remember; any extra arguments are forwarded
to streamlit as-is (e.g. `python run_dashboard.py -- --server.port 8502`).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    app_path = REPO_ROOT / "dashboard" / "app.py"
    extra_args = sys.argv[1:]
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), *extra_args]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
