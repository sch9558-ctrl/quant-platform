"""Guardrail tests for the static dashboard HTML (spec sections 33-34).

These are plain string/structure checks, not a browser render -- the
actual rendering was manually verified with Playwright screenshots
(desktop + mobile viewports, both a normal PASS run and a simulated
Fail-Closed blocked-market run) during development. What this test file
protects against is a future edit silently deleting a required section,
reintroducing a forbidden phrase, or breaking the no-external-dependency
promise that lets this page work as a plain GitHub Pages static site.
"""
from pathlib import Path

SITE_HTML = (Path(__file__).resolve().parents[2] / "site" / "index.html").read_text(encoding="utf-8")

REQUIRED_TABS = [
    "Overview", "Data Quality", "Korea Market", "US Market", "Strategies",
    "Backtests", "Paper Trading", "Risk", "Validation", "Audit Log",
]

FORBIDDEN_PHRASES = [
    "100% safe", "no loss possible", "100% profit", "100% accurate investment",
    "guaranteed return", "guaranteed profit", "cannot lose",
]


def test_site_file_exists_and_is_nonempty():
    assert len(SITE_HTML) > 1000


def test_all_required_tabs_present():
    for tab in REQUIRED_TABS:
        assert tab in SITE_HTML, f"missing required dashboard tab: {tab}"


def test_disclaimer_placeholder_wiring_present():
    # The literal disclaimer text is data-driven (comes from dashboard.json
    # at runtime, not hardcoded here) -- what must be hardcoded is the
    # wiring that displays it prominently.
    assert "disclaimer-banner" in SITE_HTML
    assert "ov.disclaimer" in SITE_HTML


def test_overview_shows_all_five_mandatory_status_fields():
    for field in ["data_integrity", "mandatory_validation_pass_rate", "pipeline_health",
                  "strategy_validation", "investment_readiness"]:
        assert field in SITE_HTML, f"overview is missing mandatory field: {field}"


def test_never_contains_forbidden_phrases():
    lowered = SITE_HTML.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, f"forbidden phrase found in static site: {phrase!r}"


def test_no_external_script_or_stylesheet_dependencies():
    # Must work as a plain GitHub Pages static site with no CDN / build
    # step -- everything is inline.
    assert "<script src=" not in SITE_HTML
    assert "<link" not in SITE_HTML or "stylesheet" not in SITE_HTML.lower()
    assert "cdn." not in SITE_HTML.lower()


def test_fetches_data_via_relative_paths_only():
    assert 'fetch("data/dashboard.json"' in SITE_HTML
    assert 'fetch("data/history.json"' in SITE_HTML
    assert "http://" not in SITE_HTML
    assert "https://" not in SITE_HTML


def test_never_places_real_orders_language_present():
    assert "never places real orders" in SITE_HTML
    assert "Live Trading is hard-disabled by default" in SITE_HTML
