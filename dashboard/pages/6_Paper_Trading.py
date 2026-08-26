from __future__ import annotations

import pandas as pd
import streamlit as st

from data_access import get_paper_broker, run_paper_rebalance

st.set_page_config(page_title="Paper Trading", layout="wide")
st.title("Paper Trading (가상 운용)")
st.caption("연구용 가상 매매입니다. 실제 주문으로 연결되지 않습니다.")

col1, col2 = st.columns(2)
market = col1.selectbox("Market", ["korea", "us"], format_func=lambda m: "한국" if m == "korea" else "미국")
demo_mode = col2.checkbox("데모 모드 (합성 데이터)", value=True)

broker = get_paper_broker(market)

c1, c2, c3 = st.columns(3)
c1.metric("Cash", f"{broker.get_cash():,.0f}")
c2.metric("Account Value", f"{broker.get_account_value():,.0f}")
c3.metric("# Positions", len(broker.get_positions()))

positions = broker.get_positions()
if positions:
    pos_df = pd.DataFrame([
        {"symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost, "market_value": p.quantity * p.avg_cost}
        for p in positions.values()
    ])
    st.subheader("현재 보유 종목")
    st.dataframe(pos_df, use_container_width=True, hide_index=True)
else:
    st.info("보유 중인 종목이 없습니다.")

equity_curve = broker.get_equity_curve()
if not equity_curve.empty:
    st.subheader("Equity Curve")
    st.line_chart(equity_curve)

fills = broker.get_fill_history()
if fills:
    st.subheader("체결 내역")
    fills_df = pd.DataFrame([
        {"date": f.filled_at, "symbol": f.symbol, "side": f.side, "quantity": f.quantity,
         "price": f.price, "commission": f.commission, "tax_or_fee": f.tax_or_fee, "reason": f.reason}
        for f in fills
    ])
    st.dataframe(fills_df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

st.divider()
st.subheader("오늘의 리밸런싱 실행")
top_n = st.slider("후보 종목 수", 3, 20, 10)
if st.button("스캔 후 동일비중 리밸런싱 실행", type="primary"):
    with st.spinner("실행 중..."):
        try:
            _, scan, results = run_paper_rebalance(market, demo=demo_mode, top_n=top_n)
        except Exception as e:
            st.error(f"실행 실패: {e}")
            st.stop()
    st.success(f"{len(results)}건의 주문이 처리되었습니다. 페이지를 새로고침해 결과를 확인하세요.")

if st.button("파산 초기화 (리셋)"):
    broker.reset()
    st.success("Paper Trading 상태가 초기화되었습니다.")
