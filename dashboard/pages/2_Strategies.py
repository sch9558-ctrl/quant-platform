from __future__ import annotations

import streamlit as st

from data_access import enabled_strategy_ids, run_quick_backtest

st.set_page_config(page_title="Strategies", layout="wide")
st.title("Strategies — Backtest")

col1, col2, col3 = st.columns(3)
strategy_id = col1.selectbox("Strategy", enabled_strategy_ids())
market = col2.selectbox("Market", ["korea", "us"], format_func=lambda m: "한국" if m == "korea" else "미국")
demo_mode = col3.checkbox("데모 모드 (합성 데이터)", value=True)

col4, col5 = st.columns(2)
start = col4.text_input("시작일", value="2015-01-01")
end = col5.text_input("종료일 (비우면 오늘)", value="")

if st.button("백테스트 실행", type="primary"):
    with st.spinner("백테스트 실행 중... (합성 데이터 기준 수 초 소요)"):
        try:
            result = run_quick_backtest(strategy_id, market, demo=demo_mode, start=start, end=end or None)
        except Exception as e:
            st.error(f"백테스트 실패: {e}")
            st.stop()

    if result.equity_curve.empty:
        st.warning("생성된 시그널이 없습니다 (전략/기간/유니버스 조합을 확인하세요).")
        st.stop()

    from quant.analytics.benchmark import buy_and_hold_equity_curve
    from quant.analytics.metrics import compute_metrics
    from quant.analytics.visualization import plot_drawdown, plot_equity_curve, plot_rolling_sharpe

    metrics = compute_metrics(result.equity_curve, result.daily_returns, result.weights,
                               {}, result.turnover)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("CAGR", f"{metrics.cagr:.1%}")
    m2.metric("Sharpe", f"{metrics.sharpe:.2f}")
    m3.metric("Sortino", f"{metrics.sortino:.2f}")
    m4.metric("Max Drawdown", f"{metrics.max_drawdown:.1%}")
    m5.metric("Calmar", f"{metrics.calmar:.2f}")

    m6, m7, m8, m9 = st.columns(4)
    m6.metric("Trades", metrics.num_trades)
    m7.metric("Win Rate", f"{metrics.win_rate:.0%}" if metrics.win_rate is not None else "N/A")
    m8.metric("Avg Turnover", f"{metrics.avg_turnover:.1%}")
    m9.metric("Exposure", f"{metrics.exposure:.1%}")

    st.pyplot(plot_equity_curve(result.equity_curve))
    st.pyplot(plot_drawdown(result.equity_curve))
    st.pyplot(plot_rolling_sharpe(result.daily_returns))
else:
    st.info("옵션을 선택하고 '백테스트 실행'을 눌러주세요. (config/strategies.yaml에 등록된 전략만 표시됩니다)")
