from __future__ import annotations

import streamlit as st

from data_access import candidates_to_frame, run_scan

st.set_page_config(page_title="Market Scanner", layout="wide")
st.title("Market Scanner")

col1, col2, col3 = st.columns(3)
market = col1.selectbox("Market", ["korea", "us"], format_func=lambda m: "한국" if m == "korea" else "미국")
as_of = col2.date_input("기준일")
demo_mode = col3.checkbox("데모 모드 (합성 데이터)", value=True)

top_n = st.slider("표시할 후보 종목 수", 5, 50, 20)

if st.button("스캔 실행", type="primary"):
    with st.spinner("스캔 중..."):
        try:
            scan = run_scan(market, as_of.strftime("%Y-%m-%d"), demo=demo_mode, top_n=top_n)
        except Exception as e:
            st.error(f"스캔 실패: {e}")
            st.stop()

    if scan.regime is not None:
        c1, c2, c3 = st.columns(3)
        c1.metric("Trend", scan.regime.trend_regime)
        c2.metric("Volatility", scan.regime.volatility_regime)
        c3.metric("Risk", scan.regime.risk_regime)

    st.caption(f"Universe size: {scan.universe_size} / 데이터 품질 제외: {len(scan.excluded_for_quality)}")

    df = candidates_to_frame(scan)
    if df.empty:
        st.info("조건을 만족하는 후보가 없습니다.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Candidate Ranking")
        import matplotlib

        matplotlib.use("Agg")
        from quant.analytics.visualization import plot_candidate_ranking

        fig = plot_candidate_ranking(df, score_col="composite_score", label_col="symbol", top_n=min(20, len(df)))
        st.pyplot(fig)
else:
    st.info("위 옵션을 선택하고 '스캔 실행' 버튼을 눌러주세요.")
