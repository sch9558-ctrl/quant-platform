#!/usr/bin/env python3
"""Generate backend-authoritative actionable signals for the React dashboard."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from quant.pipeline.daily_pipeline import build_actionable_signals, write_actionable_signals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", default="site/data/dashboard.json")
    ap.add_argument("--consensus", default="site/data/consensus_accuracy.json")
    ap.add_argument("--output", default="site/data/actionable_signals.json")
    ap.add_argument("--krw-capital", type=float, default=10_000_000)
    ap.add_argument("--usd-capital", type=float, default=10_000)
    args = ap.parse_args()

    dashboard = json.loads(Path(args.dashboard).read_text(encoding="utf-8"))
    cp = Path(args.consensus)
    consensus = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    payload = build_actionable_signals(
        dashboard,
        consensus,
        portfolio_values={"korea": args.krw_capital, "us": args.usd_capital},
    )
    out = write_actionable_signals(payload, args.output)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
