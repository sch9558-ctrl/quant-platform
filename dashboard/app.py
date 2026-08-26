"""Home page (spec section 22). Run with:

    streamlit run dashboard/app.py

Other pages live under dashboard/pages/ and are picked up automatically by
Streamlit's multipage app mechanism (sidebar navigation).
"""
from __future__ import annotations

import streamlit as st

from data_access import candidates_to_frame, load_experiments, run_scan

st.set_page_config(page_title="Quant Research Platform", layout="wide")

st.title("Quant Research & Trading Platform")
st.caption("한국(KOSPI/KOSDAQ) + 미국(NYSE/NASDAQ/AMEX) 리서치 파이프라인 · 연구 전용, 실거래 비활성화")

with st.sidebar:
    st.header("설정")
    demo_mode = st.checkbox(
        "데모 모드 (합성 데이터 사용)", value=True,
        help="실데이터(pykrx/yfinance)에 접근 가능한 환경이라면 해제하세요. "
             "이 체크박스가 켜져 있으면 실제 시장 데이터 대신 오프라인 합성 데이터를 사용합니다.",
    )
    as_of = st.date_input("기준일 (as of)")

st.subheader("오늘의 시장 현황")
col_kr, col_us = st.columns(2)

for col, market, label in ((col_kr, "korea", "한국"), (col_us, "us", "미국")):
    with col:
        st.markdown(f"### {label}")
        try:
            scan = run_scan(market, as_of.strftime("%Y-%m-%d"), demo=demo_mode, top_n=10)
        except Exception as e:
            st.error(f"스캔 실패: {e}")
            continue

        if scan.regime is not None:
            st.metric("Market Regime", scan.regime.summary_label())
        st.caption(f"Universe: {scan.universe_size}종목")

        df = candidates_to_frame(scan)
        if df.empty:
            st.info("후보 종목이 없습니다.")
        else:
            st.dataframe(
                df[["symbol", "name", "price", "ret_20d", "signal", "composite_score"]].head(10),
                use_container_width=True, hide_index=True,
            )

st.divider()
st.subheader("최근 실험 (Research DB)")
recent = load_experiments(limit=10)
if recent.empty:
    st.info("아직 저장된 실험이 없습니다. `python run_research.py` 를 먼저 실행해 보세요.")
else:
    st.dataframe(recent, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "⚠️ 이 대시보드는 연구용 정량 모델의 산출물을 보여줍니다. 투자 자문이 아니며, "
    "실제 주문으로 자동 연결되지 않습니다. LIVE_TRADING은 기본적으로 비활성화되어 있습니다."
)
