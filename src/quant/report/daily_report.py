"""Daily Research Report (spec section 18).

Assembles the outputs of the scanner, regime detector, strategy ranking,
and portfolio constructor into one human-readable Markdown report. This is
a *research* artifact -- it never places or even proposes a specific,
ready-to-click order, and every report carries an explicit disclaimer to
that effect (spec: "이것은 연구용 모델 결과이며 실제 주문으로 연결하지 않는다").
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant import config
from quant.portfolio.constructor import PortfolioAllocation
from quant.scanner.scanner import ScanResult

_TREND_LABEL_KO = {"bull": "Bull (상승)", "bear": "Bear (하락)", "sideways": "Neutral (횡보)"}


def _market_section(scan: ScanResult | None, market_label: str, top_n: int = 10) -> str:
    lines = [f"## {market_label} Candidates", ""]
    if scan is None:
        lines.append("_스캔 결과 없음_")
        return "\n".join(lines)

    if scan.regime is not None:
        lines.append(f"**Market Regime:** {scan.regime.summary_label()}")
        if scan.regime.index_return_6m is not None:
            lines.append(f"- 6개월 지수 수익률: {scan.regime.index_return_6m:+.1%}")
        if scan.regime.index_vol_annualized is not None:
            lines.append(f"- 연환산 변동성: {scan.regime.index_vol_annualized:.1%}")
        lines.append("")

    lines.append(f"Universe: {scan.universe_size}종목 (데이터 품질 이슈로 제외: {len(scan.excluded_for_quality)}종목)")
    lines.append("")

    for i, c in enumerate(scan.top_candidates[:top_n], 1):
        lines.append(f"{i}. **{c.symbol}** ({c.name})")
        price_str = f"{c.price:,.2f}"
        ret_str = f"{c.recent_return_20d:+.1%}" if c.recent_return_20d is not None else "N/A"
        lines.append(f"   - 현재가: {price_str} / 최근 20일 수익률: {ret_str}")
        mr = f"{c.momentum_rank:.2f}" if c.momentum_rank is not None else "N/A"
        tr = f"{c.trend_score:.2f}" if c.trend_score is not None else "N/A"
        vol_s = f"{c.volume_score:.2f}" if c.volume_score is not None else "N/A"
        volat = f"{c.volatility:.1%}" if c.volatility is not None else "N/A"
        rs = f"{c.relative_strength:.1%}" if c.relative_strength is not None else "N/A"
        lines.append(f"   - Momentum Rank: {mr} / Trend Score: {tr} / Volume Score: {vol_s} / Volatility: {volat} / Relative Strength: {rs}")
        lines.append(f"   - Signal: `{c.signal}` / 예상 거래비용: {c.expected_cost_bps:.1f}bp / Risk Score: {c.risk_score:.2f} / 종합 Score: {c.composite_score:.3f}")
        edge = c.historical_signal_edge
        if edge.get("n_obs", 0) >= 5:
            lines.append(
                f"   - 과거 유사 Signal 성과 (n={edge['n_obs']}): 평균 20일 수익률 {edge['mean_fwd_return']:+.1%}, "
                f"승률 {edge['win_rate']:.0%}"
            )
        lines.append("")

    return "\n".join(lines)


def _strategy_section(ranking_df: pd.DataFrame | None, top_n: int = 5) -> str:
    lines = ["## Best Strategies", ""]
    if ranking_df is None or ranking_df.empty:
        lines.append("_전략 랭킹 결과 없음_")
        return "\n".join(lines)

    for i, (strategy_id, row) in enumerate(ranking_df.head(top_n).iterrows(), 1):
        flag = "" if row.get("meets_minimum_requirements", True) else " ⚠ (표본 부족)"
        warn = row.get("overfitting_warnings") or []
        warn_str = f" — 과최적화 경고: {'; '.join(warn)}" if warn else ""
        composite = row.get("composite_score")
        composite_str = f"{composite:.3f}" if composite is not None and pd.notna(composite) else "N/A"
        lines.append(
            f"{i}. **{strategy_id}** [{row.get('market', '')}] "
            f"— Composite Score: {composite_str}{flag}{warn_str}"
        )
    return "\n".join(lines)


def _portfolio_section(allocation: PortfolioAllocation | None) -> str:
    lines = ["## Portfolio Suggestions", ""]
    if allocation is None:
        lines.append("_포트폴리오 제안 없음_")
        return "\n".join(lines)

    lines.append(f"- Cash: {allocation.cash_weight:.0%}")
    for market, w in sorted(allocation.by_market.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {market.capitalize()}: {w:.0%}")
    lines.append("")
    lines.append("종목별 비중:")
    for symbol, w in allocation.weights.sort_values(ascending=False).items():
        if w > 1e-6:
            lines.append(f"  - {symbol}: {w:.1%}")
    return "\n".join(lines)


def generate_daily_report(
    as_of: str,
    kr_scan: ScanResult | None = None,
    us_scan: ScanResult | None = None,
    strategy_ranking: pd.DataFrame | None = None,
    portfolio_allocation: PortfolioAllocation | None = None,
) -> str:
    kr_env = _TREND_LABEL_KO.get(kr_scan.regime.trend_regime, "N/A") if kr_scan and kr_scan.regime else "N/A"
    us_env = _TREND_LABEL_KO.get(us_scan.regime.trend_regime, "N/A") if us_scan and us_scan.regime else "N/A"

    sections = [
        f"# Daily Research Report — {as_of}",
        "",
        "## Market Environment",
        "",
        f"- Korea: {kr_env}",
        f"- US: {us_env}",
        "",
        _strategy_section(strategy_ranking),
        "",
        _market_section(kr_scan, "Korea"),
        "",
        _market_section(us_scan, "US"),
        "",
        _portfolio_section(portfolio_allocation),
        "",
        "---",
        "",
        "> **주의**: 이 리포트는 연구용 정량 모델의 산출물이며 투자 자문이나 매매 신호가 아닙니다. "
        "실제 주문으로 자동 연결되지 않으며, 모든 투자 판단과 책임은 사용자 본인에게 있습니다. "
        "이 시스템은 재무 자문사가 아니며, 여기 담긴 내용을 법률/세무/투자 자문으로 간주해서는 안 됩니다.",
    ]
    return "\n".join(sections)


def save_report(text: str, as_of: str, fmt: str = "md") -> Path:
    reports_dir = config.resolve_path(config.settings()["paths"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"daily_report_{as_of}.{fmt}"
    path.write_text(text, encoding="utf-8")
    return path
