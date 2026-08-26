"""Framework-agnostic data access helpers for the Streamlit dashboard.

Kept separate from the actual Streamlit page files (which only import this
module and call `st.*` rendering functions) so this logic is plain,
unit-testable Python -- Streamlit script files themselves are awkward to
unit test directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# allow running `streamlit run dashboard/app.py` directly without an editable
# install, by making sure `src/` is on sys.path.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from quant.backtest.engine import Backtester
from quant.data.factory import get_provider
from quant.research_db.db import ResearchDB
from quant.scanner.scanner import DailyScanner, ScanResult
from quant.strategy import registry


def run_scan(market: str, as_of: str, demo: bool = True, top_n: int = 20) -> ScanResult:
    provider = get_provider(market, demo=demo)
    scanner = DailyScanner(market, provider)
    return scanner.run(as_of=as_of, top_n=top_n)


def candidates_to_frame(scan: ScanResult) -> pd.DataFrame:
    rows = []
    for c in scan.top_candidates:
        rows.append({
            "symbol": c.symbol, "name": c.name, "price": c.price,
            "ret_20d": c.recent_return_20d, "momentum_rank": c.momentum_rank,
            "trend_score": c.trend_score, "volume_score": c.volume_score,
            "volatility": c.volatility, "relative_strength": c.relative_strength,
            "signal": c.signal, "expected_cost_bps": c.expected_cost_bps,
            "risk_score": c.risk_score, "composite_score": c.composite_score,
        })
    return pd.DataFrame(rows)


def load_experiments(market: str | None = None, strategy_id: str | None = None, limit: int = 200) -> pd.DataFrame:
    db = ResearchDB()
    return db.query_experiments(market=market, strategy_id=strategy_id, limit=limit)


def load_experiment_detail(experiment_id: str):
    db = ResearchDB()
    return db.get_experiment(experiment_id)


def run_quick_backtest(strategy_id: str, market: str, demo: bool = True, start: str | None = None, end: str | None = None):
    provider = get_provider(market, demo=demo)
    symbols_info = provider.list_symbols()
    equities = [s.symbol for s in symbols_info if s.asset_type == "equity"][:40]
    start = start or "2015-01-01"
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    ohlcv_map = {s: provider.get_ohlcv(s, start, end) for s in equities}
    ohlcv_map = {s: df for s, df in ohlcv_map.items() if df is not None and not df.empty}

    strategy = registry.build_strategy(strategy_id)
    bt = Backtester(market)
    result = bt.run(strategy, ohlcv_map, start=start, end=end)
    return result


def enabled_strategy_ids() -> list[str]:
    return registry.enabled_strategy_ids()


def get_paper_broker(market: str):
    from quant.broker.kr_paper import KoreaPaperBroker
    from quant.broker.us_paper import USPaperBroker
    return KoreaPaperBroker() if market == "korea" else USPaperBroker()


def run_paper_rebalance(market: str, demo: bool = True, top_n: int = 10):
    """Simple equal-weight paper rebalance across today's top scanner
    candidates -- a convenience for the dashboard's Paper Trading page.
    `run_paper.py` (repo root) is the more complete CLI version that sizes
    positions via the full `PortfolioConstructor` instead of flat equal
    weight."""
    provider = get_provider(market, demo=demo)
    scanner = DailyScanner(market, provider)
    as_of = pd.Timestamp.today().strftime("%Y-%m-%d")
    scan = scanner.run(as_of=as_of, top_n=top_n)

    broker = get_paper_broker(market)
    if not scan.top_candidates:
        return broker, scan, []

    weight_each = 1.0 / len(scan.top_candidates) * 0.9  # keep 10% cash buffer
    target_weights = {c.symbol: weight_each for c in scan.top_candidates}
    prices = {c.symbol: c.price for c in scan.top_candidates}
    results = broker.rebalance_to_target_weights(target_weights, prices)
    broker.record_daily_equity(prices)
    return broker, scan, results
