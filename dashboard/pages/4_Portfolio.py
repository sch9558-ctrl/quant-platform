from __future__ import annotations

import pandas as pd
import streamlit as st

from data_access import candidates_to_frame, run_scan

st.set_page_config(page_title="Portfolio", layout="wide")
st.title("Portfolio Construction (시뮬레이션)")

st.caption("스캐너 후보 종목을 대상으로 다양한 비중 산정 방식과 제약조건을 실험해볼 수 있습니다.")

col1, col2, col3 = st.columns(3)
market = col1.selectbox("Market", ["korea", "us"], format_func=lambda m: "한국" if m == "korea" else "미국")
as_of = col2.date_input("기준일")
demo_mode = col3.checkbox("데모 모드 (합성 데이터)", value=True)

method = st.selectbox(
    "Weighting Method",
    ["equal_weight", "signal_weight", "volatility_weight", "inverse_volatility", "risk_parity"],
)

c1, c2, c3, c4, c5 = st.columns(5)
max_position = c1.slider("종목당 최대 비중", 0.01, 1.0, 0.10)
max_sector = c2.slider("섹터당 최대 비중", 0.05, 1.0, 0.30)
max_market = c3.slider("시장당 최대 비중", 0.05, 1.0, 0.70)
min_cash = c4.slider("최소 현금 비중", 0.0, 0.9, 0.05)
max_gross = c5.slider("최대 총 노출", 0.1, 1.0, 1.0)

if st.button("포트폴리오 계산", type="primary"):
    from quant.portfolio.constructor import PortfolioConstraints, PortfolioConstructor, PortfolioItem

    try:
        scan = run_scan(market, as_of.strftime("%Y-%m-%d"), demo=demo_mode, top_n=15)
    except Exception as e:
        st.error(f"스캔 실패: {e}")
        st.stop()

    df = candidates_to_frame(scan)
    if df.empty:
        st.warning("후보 종목이 없어 포트폴리오를 구성할 수 없습니다.")
        st.stop()

    items = [
        PortfolioItem(
            symbol=row["symbol"], market=market, strategy_id="scanner",
            sector=None, signal_strength=max(row["composite_score"], 0.0),
            volatility=row["volatility"] if pd.notna(row["volatility"]) else 0.2,
        )
        for _, row in df.iterrows()
    ]

    constraints = PortfolioConstraints(
        max_position_weight=max_position, max_sector_weight=max_sector,
        max_strategy_weight=1.0, max_market_weight=max_market,
        min_cash_weight=min_cash, max_gross_exposure=max_gross,
    )
    pc = PortfolioConstructor(method=method, constraints=constraints)
    allocation = pc.compute_weights(items)

    st.subheader("결과")
    st.metric("Cash", f"{allocation.cash_weight:.1%}")

    weights_df = allocation.weights.sort_values(ascending=False).rename("weight").to_frame()
    weights_df = weights_df[weights_df["weight"] > 1e-6]
    st.dataframe(weights_df, use_container_width=True)

    from quant.analytics.visualization import plot_portfolio_allocation

    pie_data = {**{k: v for k, v in weights_df["weight"].items()}, "Cash": allocation.cash_weight}
    st.pyplot(plot_portfolio_allocation(pie_data))

    if allocation.notes:
        st.info("적용된 제약: " + "; ".join(sorted(set(allocation.notes))))
else:
    st.info("옵션을 선택하고 '포트폴리오 계산'을 눌러주세요.")
