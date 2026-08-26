"""Smoke tests: does each Streamlit page script run top-to-bottom without
raising an exception? This does not check visual layout, just that the
script executes cleanly against demo (synthetic) data -- the default state
a brand new install would be in.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "dashboard"


def test_home_page_runs_without_exception():
    at = AppTest.from_file(str(_DASHBOARD_DIR / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception


@pytest.mark.parametrize("page_name", [
    "1_Market_Scanner.py",
    "2_Strategies.py",
    "3_Experiments.py",
    "4_Portfolio.py",
    "5_Risk.py",
])
def test_page_runs_without_exception_before_button_click(page_name):
    at = AppTest.from_file(str(_DASHBOARD_DIR / "pages" / page_name), default_timeout=60)
    at.run()
    assert not at.exception
