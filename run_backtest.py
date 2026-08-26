#!/usr/bin/env python3
"""Single-strategy Walk-Forward Backtest CLI (spec sections 8-10 / CLI
section 27).

Usage:
    python run_backtest.py --strategy ma_crossover --market korea
    python run_backtest.py --strategy cs_momentum --market us --param-search --save

Runs one strategy through Walk-Forward Analysis (rolling In-Sample ->
Validation -> Out-of-Sample folds, per config/validation.yaml) against the
screened universe for a market, prints fold-by-fold and aggregate
Out-of-Sample metrics plus an Overfitting Detection assessment, and
optionally records the run as a reproducible experiment in the Research DB
(git commit hash, dataset fingerprint, params, costs -- spec section 19).

`--param-search` additionally runs the parameter-stability search (spec
section 9: prefers a stable neighborhood of parameters over an isolated
best-scoring spike) instead of using the strategy's config-file default
parameters -- this is slower (a full grid search per fold) so it is opt-in
rather than the default.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import itertools  # noqa: E402

import pandas as pd  # noqa: E402

from quant import config  # noqa: E402
from quant.data.factory import get_provider  # noqa: E402
from quant.pipeline.research_pipeline import _build_backtest_inputs  # noqa: E402
from quant.quality.pipeline_gate import run_gated_scan  # noqa: E402
from quant.ranking.overfitting import assess_overfitting  # noqa: E402
from quant.research_db.db import ResearchDB  # noqa: E402
from quant.research_db.models import ExperimentRecord, current_code_version, dataset_version_tag  # noqa: E402
from quant.strategy import registry  # noqa: E402
from quant.validation.walk_forward import WalkForwardAnalyzer  # noqa: E402


def _param_combo_count(strategy_id: str, param_search: bool) -> int:
    if not param_search:
        return 1
    grid = registry.param_grid_for(strategy_id)
    if not grid:
        return 1
    n = 1
    for values in grid.values():
        n *= len(values)
    return n


def _print_metrics(label: str, m) -> None:
    print(
        f"  {label:10s}  CAGR={m.cagr:+.1%}  Sharpe={m.sharpe:.2f}  Sortino={m.sortino:.2f}  "
        f"MaxDD={m.max_drawdown:.1%}  Calmar={m.calmar:.2f}  Trades={m.num_trades}  "
        f"Turnover={m.avg_turnover:.2f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", required=True, help="Strategy id from config/strategies.yaml")
    parser.add_argument("--market", choices=["korea", "us"], required=True)
    parser.add_argument("--top-n-universe", type=int, default=40, help="How many screened symbols to backtest against")
    parser.add_argument("--lookback-years", type=int, default=8)
    parser.add_argument("--param-search", action="store_true", help="Run the full parameter-stability grid search")
    parser.add_argument("--save", action="store_true", help="Save this run as an experiment in the Research DB")
    parser.add_argument(
        "--demo", dest="demo", action="store_true", default=True,
        help="Use synthetic offline data (the default).",
    )
    parser.add_argument(
        "--real", dest="demo", action="store_false",
        help="Use REAL market data (pykrx / yfinance) instead of the synthetic "
             "offline dataset. Requires network access to KRX / Yahoo Finance.",
    )
    parser.add_argument("--as-of", default=None, help="Override the as-of date (YYYY-MM-DD); default: today.")
    args = parser.parse_args()

    as_of = args.as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
    provider = get_provider(args.market, demo=args.demo)

    # Today's screened universe still goes through the Fail-Closed Data
    # Quality gate (spec section 2) -- a manual/exploratory backtest should
    # not silently build its symbol universe from data that failed
    # mandatory validation. (The multi-year backtest history fetched below
    # by `_build_backtest_inputs` is a separate concern -- historical data
    # quality over an 8-year window -- not yet covered by this same gate;
    # see run_backtest.py's module docstring / project TODOs.)
    gated = run_gated_scan(args.market, provider=provider, as_of=as_of, demo=args.demo, top_n=args.top_n_universe)
    if gated.blocked:
        print(f"DATA VALIDATION: FAIL\n⛔ {gated.block_reason}")
        print(f"No backtest run for {args.market} as_of={as_of} -- today's screened universe could not be validated.")
        return 1
    scan = gated.scan
    symbols = [c.symbol for c in scan.all_candidates] or [c.symbol for c in scan.top_candidates]
    if not symbols:
        print(f"No symbols passed screening for {args.market} as_of={as_of} -- nothing to backtest.")
        return 1

    print(f"Backtesting '{args.strategy}' on {args.market} against {len(symbols)} screened symbols (as_of={as_of})")
    ohlcv_map, feature_map, benchmark_close = _build_backtest_inputs(
        args.market, provider, symbols, as_of, args.lookback_years,
    )
    start = (pd.Timestamp(as_of) - pd.DateOffset(years=args.lookback_years)).strftime("%Y-%m-%d")

    analyzer = WalkForwardAnalyzer(args.market)
    wf = analyzer.run(
        args.strategy, ohlcv_map, feature_map=feature_map, benchmark_close=benchmark_close,
        start=start, end=as_of, use_param_search=args.param_search,
    )

    if not wf.fold_results:
        print("No walk-forward folds could be generated (insufficient history).")
        return 1

    print(f"\n{len(wf.fold_results)} walk-forward fold(s):")
    for fr in wf.fold_results:
        print(f"\nFold {fr.fold.fold_id}: IS[{fr.fold.is_start.date()}..{fr.fold.val_end.date()}] "
              f"OOS[{fr.fold.oos_start.date()}..{fr.fold.oos_end.date()}]  params={fr.chosen_params}")
        _print_metrics("IS", fr.is_metrics)
        _print_metrics("OOS", fr.oos_metrics)
        if fr.stability is not None:
            print(f"    parameter stability: is_stable={fr.stability.is_stable} "
                  f"(own_score={fr.stability.own_score:.2f}, "
                  f"neighbor_avg_score={fr.stability.neighbor_avg_score:.2f}, "
                  f"neighbor_count={fr.stability.neighbor_count})")

    print("\nAggregate (chained) Out-of-Sample performance:")
    _print_metrics("AGG-OOS", wf.aggregate_oos_metrics)

    avg_is_sharpe = sum(fr.is_metrics.sharpe for fr in wf.fold_results) / len(wf.fold_results)
    avg_oos_sharpe = sum(fr.oos_metrics.sharpe for fr in wf.fold_results) / len(wf.fold_results)
    n_trades = sum(fr.oos_metrics.num_trades for fr in wf.fold_results)
    n_combos = _param_combo_count(args.strategy, args.param_search)
    assessment = assess_overfitting(args.strategy, avg_is_sharpe, avg_oos_sharpe, n_trades, n_combos)
    print(f"\nOverfitting risk: {assessment.risk_level.upper()}")
    for reason in assessment.reasons:
        print(f"  - {reason}")

    if args.save:
        db = ResearchDB()
        record = ExperimentRecord(
            experiment_id=f"{args.market}_{args.strategy}_{pd.Timestamp(as_of).strftime('%Y%m%d')}_manual",
            created_at=pd.Timestamp.now(),
            market=args.market, strategy_id=args.strategy,
            params=wf.fold_results[-1].chosen_params,
            universe_description=f"{len(symbols)} symbols (screened universe, top_n_universe={args.top_n_universe})",
            backtest_start=start, backtest_end=as_of,
            is_metrics=vars(wf.fold_results[-1].is_metrics),
            oos_metrics=vars(wf.fold_results[-1].oos_metrics),
            aggregate_oos_metrics=vars(wf.aggregate_oos_metrics),
            cost_config=config.costs_config(),
            code_version=current_code_version(),
            dataset_version=dataset_version_tag(args.market, symbols, start, as_of),
            composite_score=None,
            overfitting_risk=assessment.risk_level,
            notes="run_backtest.py manual run" + (" (param search)" if args.param_search else ""),
        )
        db.save_experiment(record)
        print(f"\nSaved experiment '{record.experiment_id}' to Research DB.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
