"""Daily Market Scanner orchestrator (spec section 2): ties Universe Engine
-> Feature Engine -> Regime Detection -> Screener together into the single
entry point `run_scan.py` calls for each market.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant.data.base import MarketDataProvider
from quant.data.quality import check_ohlcv
from quant.features.engine import FeatureEngine
from quant.features import fundamental as fnd
from quant.regime.detector import RegimeDetector, RegimeResult, compute_breadth
from quant.scanner.screener import CandidateResult, score_candidates, top_candidates
from quant.universe.engine import UniverseEngine, UniverseSnapshot
from quant.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_INDEX = {"korea": "KOSPI", "us": "SP500"}


@dataclass
class ScanResult:
    market: str
    as_of: pd.Timestamp
    regime: RegimeResult
    universe_size: int
    top_candidates: list[CandidateResult]
    all_candidates: list[CandidateResult]
    excluded_for_quality: list[str]


class DailyScanner:
    def __init__(self, market: str, provider: MarketDataProvider):
        assert market in ("korea", "us")
        self.market = market
        self.provider = provider
        self.universe_engine = UniverseEngine(market, provider)
        self.feature_engine = FeatureEngine(market)
        self.regime_detector = RegimeDetector(market)

    def run(self, as_of: str, lookback_days: int = 400, top_n: int = 20) -> ScanResult:
        snapshot: UniverseSnapshot = self.universe_engine.build(as_of)
        included = snapshot.included_symbols()
        logger.info("Scanner[%s] universe size after filters: %d", self.market, len(included))

        lookback_start = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(lookback_days)).strftime("%Y-%m-%d")
        ohlcv_map = self.provider.get_ohlcv_bulk(included, lookback_start, as_of)

        excluded_for_quality = []
        clean_ohlcv_map = {}
        for sym, df in ohlcv_map.items():
            issues = check_ohlcv(sym, df)
            if any(i.severity == "FATAL" for i in issues):
                excluded_for_quality.append(sym)
                continue
            clean_ohlcv_map[sym] = df

        index_symbol = _DEFAULT_INDEX[self.market]
        index_ohlcv = self.provider.get_index_ohlcv(index_symbol, lookback_start, as_of)

        benchmark_close = index_ohlcv["close"] if not index_ohlcv.empty else None
        feature_map = self.feature_engine.compute_panel(clean_ohlcv_map, benchmark_close=benchmark_close)
        rank_wide = self.feature_engine.cross_sectional_momentum_rank(feature_map, ret_col="ret_120d")
        feature_map = self.feature_engine.attach_momentum_rank(feature_map, rank_wide)

        frame = snapshot.to_frame().set_index("symbol")
        symbol_meta = {
            sym: {"name": frame.loc[sym, "name"], "exchange": frame.loc[sym, "exchange"],
                  "asset_type": frame.loc[sym, "asset_type"]}
            for sym in feature_map if sym in frame.index
        }

        equity_symbols = [s for s in feature_map if symbol_meta.get(s, {}).get("asset_type") == "equity"]
        fundamental_scores = None
        try:
            fund_df = self.provider.get_fundamentals(equity_symbols, as_of)
            if fund_df is not None and not fund_df.empty:
                fundamental_scores = pd.concat([
                    fnd.value_score(fund_df), fnd.quality_score(fund_df), fnd.growth_score(fund_df),
                ], axis=1)
        except Exception as e:
            logger.warning("Fundamental scoring skipped for %s: %s", self.market, e)

        candidates = score_candidates(self.market, feature_map, clean_ohlcv_map, symbol_meta, fundamental_scores)

        breadth = compute_breadth(clean_ohlcv_map)
        regime = self.regime_detector.detect(index_ohlcv, breadth) if not index_ohlcv.empty else None

        return ScanResult(
            market=self.market, as_of=pd.Timestamp(as_of), regime=regime,
            universe_size=len(included), top_candidates=top_candidates(candidates, top_n),
            all_candidates=candidates, excluded_for_quality=excluded_for_quality,
        )


def format_report(result: ScanResult) -> str:
    lines = []
    market_label = "한국 (Korea)" if result.market == "korea" else "미국 (US)"
    lines.append(f"=== {market_label} Market Scan — {result.as_of.date()} ===")
    if result.regime is not None:
        lines.append(f"Market Regime: {result.regime.summary_label()}  "
                      f"(6m return: {result.regime.index_return_6m:+.1%}, "
                      f"ann. vol: {result.regime.index_vol_annualized:.1%})"
                      if result.regime.index_return_6m is not None and result.regime.index_vol_annualized is not None
                      else f"Market Regime: {result.regime.summary_label()}")
    lines.append(f"Universe size: {result.universe_size} (excluded for data quality: {len(result.excluded_for_quality)})")
    lines.append("")
    lines.append(f"Top {len(result.top_candidates)} Candidates:")
    for i, c in enumerate(result.top_candidates, 1):
        lines.append(
            f"{i}. {c.symbol} ({c.name})  price={c.price:,.2f}  "
            f"ret20d={c.recent_return_20d:+.1%}" if c.recent_return_20d is not None else
            f"{i}. {c.symbol} ({c.name})  price={c.price:,.2f}"
        )
        lines.append(
            f"    momentum_rank={c.momentum_rank:.2f}  trend={c.trend_score:.2f}  "
            f"volume={c.volume_score:.2f}  vol={c.volatility:.1%}  rs={c.relative_strength}  "
            f"signal={c.signal}  est_cost={c.expected_cost_bps:.1f}bps  "
            f"risk={c.risk_score:.2f}  score={c.composite_score:.3f}"
            if c.trend_score is not None and c.volume_score is not None and c.volatility is not None else
            f"    signal={c.signal}  score={c.composite_score:.3f}"
        )
        edge = c.historical_signal_edge
        if edge.get("n_obs", 0) >= 5:
            lines.append(
                f"    historical similar-signal edge (n={edge['n_obs']}): "
                f"mean fwd 20d return={edge['mean_fwd_return']:+.1%}, win rate={edge['win_rate']:.0%}"
            )
    return "\n".join(lines)
