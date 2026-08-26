"""Guardrail tests for the static dashboard HTML (spec sections 33-34).

These are plain string/structure checks, not a browser render -- the
actual rendering was manually verified with Playwright screenshots
(desktop + mobile viewports, both a normal PASS run and a simulated
Fail-Closed blocked-market run) during development. What this test file
protects against is a future edit silently deleting a required section,
reintroducing a forbidden phrase, or breaking the no-external-dependency
promise that lets this page work as a plain GitHub Pages static site.

The UI is Korean. Two things that must survive translation and are
therefore asserted explicitly:

* the **English disclaimer sentence** the spec mandates verbatim still
  reaches the page (it arrives in the JSON payload and is rendered next
  to the Korean version, never replaced by it); and
* the forbidden-claim list is checked in **both languages** -- a
  translated "100% 안전" would sail past an English-only check.
"""
from pathlib import Path

SITE_HTML = (Path(__file__).resolve().parents[2] / "site" / "index.html").read_text(encoding="utf-8")

REQUIRED_TABS = [
    "종합", "데이터 품질", "한국 시장", "미국 시장", "전략",
    "백테스트", "모의투자", "리스크", "검증", "감사 로그",
]

FORBIDDEN_PHRASES = [
    # English
    "100% safe", "no loss possible", "100% profit", "100% accurate investment",
    "guaranteed return", "guaranteed profit", "cannot lose",
    # Korean -- the same claims, which an English-only list would miss
    "100% 안전", "손실 없음", "손실이 불가능", "100% 수익", "수익 보장",
    "원금 보장", "무조건 수익", "절대 손실",
]


def test_site_file_exists_and_is_nonempty():
    assert len(SITE_HTML) > 1000


def test_all_required_tabs_present():
    for tab in REQUIRED_TABS:
        assert tab in SITE_HTML, f"missing required dashboard tab: {tab}"


def test_page_declares_korean_language():
    assert 'lang="ko"' in SITE_HTML


def test_disclaimer_placeholder_wiring_present():
    # The mandated English sentence is data-driven (it comes from
    # dashboard.json at runtime); what must be hardcoded is the wiring that
    # displays it prominently, plus the Korean rendering beside it.
    assert "disclaimer-banner" in SITE_HTML
    assert "ov.disclaimer" in SITE_HTML
    assert "DISCLAIMER_KO" in SITE_HTML


def test_korean_disclaimer_states_both_halves_of_the_claim():
    """The Korean text must carry the *whole* meaning, not just the flattering
    half: that validation passing says nothing about predicting returns, and
    nothing about loss being impossible."""
    assert "데이터 검증 100%" in SITE_HTML
    assert "예측할 수 있다는 뜻이 아니며" in SITE_HTML
    assert "손실이 불가능하다는 뜻도 아닙니다" in SITE_HTML


def test_overview_shows_all_five_mandatory_status_fields():
    for field in ["data_integrity", "mandatory_validation_pass_rate", "pipeline_health",
                  "strategy_validation", "investment_readiness"]:
        assert field in SITE_HTML, f"overview is missing mandatory field: {field}"


#: The disclaimer is the one sanctioned place where these words legitimately
#: appear -- it exists precisely to *deny* the claims ("...does not mean that
#: loss is impossible"). A plain substring scan cannot tell a claim from its
#: negation, so the disclaimer sentences are removed before scanning rather
#: than the forbidden list being weakened to let them through.
#: Only the Korean rendering is hardcoded here; the mandated English
#: sentence arrives at runtime from dashboard.json (see
#: `test_disclaimer_placeholder_wiring_present`), so it never appears in
#: this file's own text and needs no exclusion.
DISCLAIMER_SENTENCES = [
    "미래의 투자 수익률을 100% 정확하게 예측할 수 있다는 뜻이 아니며, 손실이 불가능하다는 뜻도 아닙니다.",
]


def _scannable_text() -> str:
    text = SITE_HTML
    for sentence in DISCLAIMER_SENTENCES:
        assert sentence in text, (
            f"disclaimer sentence missing from the page, so the forbidden-phrase "
            f"exclusion is masking something else: {sentence!r}"
        )
        text = text.replace(sentence, "")
    return text.lower()


def test_never_contains_forbidden_phrases():
    scannable = _scannable_text()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in scannable, (
            f"forbidden phrase found in static site outside the disclaimer: {phrase!r}"
        )


def test_forbidden_phrase_scan_would_catch_a_real_claim():
    """Guards the guard: prove the disclaimer exclusion did not defang the
    check by leaving a hole an actual claim could slip through."""
    scannable = _scannable_text()
    assert "손실이 불가능" not in scannable, "disclaimer text should have been stripped"
    # A claim added anywhere else must still be caught.
    tampered = (SITE_HTML + "<p>이 전략은 100% 안전합니다</p>")
    for sentence in DISCLAIMER_SENTENCES:
        tampered = tampered.replace(sentence, "")
    assert "100% 안전" in tampered.lower()


def test_status_values_are_translated_for_display_only():
    """Translation must not change the value the CSS class is derived from --
    otherwise a PASS could render with FAIL styling (or no styling at all)."""
    assert "STATUS_KO" in SITE_HTML
    assert "READINESS_KO" in SITE_HTML
    # class derivation still runs on the raw value
    assert 'return "status-" + String(v)' in SITE_HTML
    assert 'return "pill pill-" + String(v)' in SITE_HTML


def test_readiness_ladder_levels_all_have_translations():
    for level in ["DATA_INVALID", "DATA_VERIFIED", "RESEARCH_VALIDATED", "OOS_VALIDATED",
                  "PAPER_TRADING", "PAPER_VERIFIED", "ELIGIBLE_FOR_MANUAL_REVIEW"]:
        assert level in SITE_HTML, f"readiness level missing from the display map: {level}"


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
    """Kept in both languages: the Korean reader needs to understand it, and
    the English phrasing is what the spec pins."""
    assert "never places real orders" in SITE_HTML
    assert "Live Trading is hard-disabled by default" in SITE_HTML
    assert "실제 주문을 절대 내지 않으며" in SITE_HTML


def test_blocked_market_banner_is_unmistakable():
    assert "데이터 검증 실패" in SITE_HTML
    assert "오늘의 투자 후보 생성 중단" in SITE_HTML
    # and must not be softened into an ordinary "nothing found today" message
    assert "전날 결과를 오늘 것처럼 재사용하는 일은 없습니다" in SITE_HTML
