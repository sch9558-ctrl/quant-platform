"""Korean React/Vite dashboard source guardrails."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
APP=(ROOT/"dashboard/src/App.jsx").read_text(encoding="utf-8")
CARD=(ROOT/"dashboard/src/components/ActionableTradeCard.jsx").read_text(encoding="utf-8")
HTML=(ROOT/"dashboard/index.html").read_text(encoding="utf-8")
VITE=(ROOT/"dashboard/vite.config.js").read_text(encoding="utf-8")

def test_dashboard_is_korean_and_react_based():
    assert 'lang="ko"' in HTML
    assert "오늘의 퀀트 매매 가이드" in APP
    assert "국내 증시" in APP and "미국 증시" in APP

def test_action_card_contains_decision_fields():
    for label in ["적정 매수가","1차 목표","2차 목표","손절 기준선","권장 보유기간","증권사/IB 리포트 검증"]:
        assert label in CARD

def test_blocked_market_does_not_reuse_stale_candidates():
    assert "데이터 검증 실패" in APP
    assert "전일 후보를 오늘 후보처럼 재사용하지 않습니다" in APP

def test_vite_build_targets_existing_cloudflare_site_directory():
    assert "outDir:'../site'" in VITE
    assert "emptyOutDir:false" in VITE

def test_ui_fetches_dashboard_and_consensus_relative_data():
    assert "data/dashboard.json" in APP
    assert "data/consensus_accuracy.json" in APP

def test_live_trading_or_guarantee_claims_not_present():
    text=(APP+CARD).lower()
    for phrase in ["수익 보장","원금 보장","100% 안전","guaranteed profit"]:
        assert phrase not in text
