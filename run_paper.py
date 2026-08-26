#!/usr/bin/env python3
"""Daily Paper Trading rebalance cycle (spec section 23 / CLI section 27).

Usage:
    python run_paper.py --market korea [--top-n 10] [--as-of 2026-08-26]
    python run_paper.py --market us --top-n 15

Runs one full "adapter-level" paper trading cycle for a single market:
    scan (Universe -> Feature -> Regime -> Screener) -> build a
    constrained portfolio allocation from today's top candidates via
    `PortfolioConstructor` -> submit the resulting buy/sell orders through
    the Paper Broker (which itself routes every single order through the
    shared `RiskManager`, exactly as a live broker adapter would have to)
    -> record today's equity mark so the paper-trading track record grows
    day by day.

This is the "more complete" CLI counterpart to the dashboard's Paper
Trading page quick-rebalance button (`dashboard/data_access.run_paper_rebalance`,
which does a simpler equal-weight-minus-cash-buffer allocation for a fast
one-click demo) -- this script goes through the real Portfolio
Construction step so the sizing respects position/sector/market caps.

SAFETY: this script can ONLY ever touch `KoreaPaperBroker` / `USPaperBroker`.
Live trading is hard-locked off in `quant.config.is_live_trading_enabled()`
(see ARCHITECTURE.md "Safety") and this script does not import, reference,
or expose any flag toward the Live broker stubs -- there is nothing here
that could turn this into a real order.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pandas as pd  # noqa: E402

from quant.broker.kr_paper import KoreaPaperBroker  # noqa: E402
from quant.broker.us_paper import USPaperBroker  # noqa: E402
from quant.data.factory import get_provider  # noqa: E402
from quant.portfolio.constructor import PortfolioConstructor, PortfolioItem  # noqa: E402
from quant.scanner.scanner import DailyScanner  # noqa: E402
from quant.utils.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def build_broker(market: str):
    return KoreaPaperBroker() if market == "korea" else USPaperBroker()


def run_paper_cycle(market: str, demo: bool, top_n: int, as_of: str | None = None) -> None:
    as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    provider = get_provider(market, demo=demo)
    scanner = DailyScanner(market, provider)
    scan = scanner.run(as_of=as_of, top_n=top_n)

    broker = build_broker(market)
    print(f"[{market}] as_of={as_of} regime={scan.regime.summary_label()} universe_size={scan.universe_size}")
    print(f"[{market}] top candidates found: {len(scan.top_candidates)}")

    if not scan.top_candidates:
        broker.record_daily_equity({}, as_of=pd.Timestamp(as_of))
        print(f"[{market}] no candidates today -- no rebalance performed.")
        return

    items = [
        PortfolioItem(
            symbol=c.symbol,
            market=market,
            strategy_id="scanner",
            sector=None,
            signal_strength=max(c.composite_score, 0.0),
            volatility=c.volatility,
        )
        for c in scan.top_candidates
    ]
    allocation = PortfolioConstructor().compute_weights(items)
    prices = {c.symbol: c.price for c in scan.top_candidates}

    results = broker.rebalance_to_target_weights(allocation.weights.to_dict(), prices)
    n_filled = sum(1 for r in results if hasattr(r, "fill_id"))
    n_rejected = len(results) - n_filled
    print(
        f"[{market}] rebalance: {n_filled} filled, {n_rejected} rejected "
        f"(target cash weight {allocation.cash_weight:.1%})"
    )

    equity = broker.record_daily_equity(prices, as_of=pd.Timestamp(as_of))
    print(
        f"[{market}] account value={equity:,.2f} cash={broker.get_cash():,.2f} "
        f"positions={len(broker.get_positions())}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", choices=["korea", "us"], required=True)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Use synthetic offline data (default: on -- this sandbox has no network access to KRX/Yahoo).",
    )
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    args = parser.parse_args()

    run_paper_cycle(args.market, demo=args.demo, top_n=args.top_n, as_of=args.as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
