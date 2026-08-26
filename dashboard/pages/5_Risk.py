from __future__ import annotations

import streamlit as st

from data_access import enabled_strategy_ids, run_quick_backtest

st.set_page_config(page_title="Risk", layout="wide")
st.title("Risk — Drawdown / Exposure / Correlation")

col1, col2, col3 = st.columns(3)
strategy_id = col1.selectbox("Strategy", enabled_strategy_ids())
market = col2.selectbox("Market", ["korea", "us"], format_func=lambda m: "한국" if m == "korea" else "미국")
demo_mode = col3.checkbox("데모 모드 (합성 데이터)", value=True)

if st.button("리스크 분석 실행", type="primary"):
    with st.spinner("계산 중..."):
        try:
            result = run_quick_backtest(strategy_id, market, demo=demo_mode)
        except Exception as e:
            st.error(f"실행 실패: {e}")
            st.stop()

    if result.equity_curve.empty:
        st.warning("생성된 시그널이 없습니다.")
        st.stop()

    from quant.analytics.metrics import drawdown_series, max_drawdown, max_drawdown_recovery_days
    from quant.analytics.visualization import plot_correlation_matrix, plot_drawdown
    from quant.ranking.monte_carlo import run_monte_carlo

    mdd = max_drawdown(result.equity_curve)
    recovery = max_drawdown_recovery_days(result.equity_curve)

    c1, c2, c3 = st.columns(3)
    c1.metric("Max Drawdown", f"{mdd:.1%}")
    c2.metric("Recovery (days)", recovery if recovery is not None else "미회복")
    c3.metric("Avg Exposure", f"{result.weights.sum(axis=1).mean():.1%}" if not result.weights.empty else "N/A")

    st.pyplot(plot_drawdown(result.equity_curve))

    if result.weights.shape[1] >= 2:
        returns_wide = result.weights.diff().fillna(0)  # placeholder correlation of position changes
        st.subheader("Position Correlation (weight changes)")
        st.pyplot(plot_correlation_matrix(returns_wide))

    st.subheader("Monte Carlo Simulation")
    mc = run_monte_carlo(result.daily_returns, n_simulations=1000, seed=0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Median Return", f"{mc.median_final_return:.1%}")
    m2.metric("Worst Case (5%)", f"{mc.worst_case_final_return:.1%}")
    m3.metric("95% Drawdown", f"{mc.drawdown_95th_percentile:.1%}")
    m4.metric("Risk of Ruin", f"{mc.risk_of_ruin:.1%}")
else:
    st.info("옵션을 선택하고 '리스크 분석 실행'을 눌러주세요.")
