from __future__ import annotations

import streamlit as st

from data_access import load_experiment_detail, load_experiments

st.set_page_config(page_title="Experiments", layout="wide")
st.title("Experiments — Research Database")

col1, col2 = st.columns(2)
market_filter = col1.selectbox("Market 필터", ["(전체)", "korea", "us"])
strategy_filter = col2.text_input("Strategy ID 필터 (비우면 전체)")

df = load_experiments(
    market=None if market_filter == "(전체)" else market_filter,
    strategy_id=strategy_filter or None,
)

if df.empty:
    st.info("저장된 실험이 없습니다. `python run_research.py` 또는 `python run_backtest.py`를 먼저 실행하세요.")
else:
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("실험 상세 보기")
    exp_id = st.selectbox("Experiment ID", df["experiment_id"].tolist())
    if exp_id:
        record = load_experiment_detail(exp_id)
        if record:
            c1, c2 = st.columns(2)
            with c1:
                st.write("**IS Metrics**")
                st.json(record.is_metrics)
            with c2:
                st.write("**OOS Metrics**")
                st.json(record.oos_metrics)
            st.write("**Params**")
            st.json(record.params)
            st.caption(f"Code version: {record.code_version} · Dataset version: {record.dataset_version}")
