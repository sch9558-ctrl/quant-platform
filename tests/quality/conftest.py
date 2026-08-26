"""Shared fixture builders for Data Quality Engine tests.

These build small, hand-computable ("known answer") long-record tables
(spec section 57) rather than relying on the synthetic market data
provider -- the whole point of these tests is to verify each validation
rule against inputs whose correct outcome a human can check by eye.
"""
from __future__ import annotations

import pandas as pd
import pytest


def make_records(rows: list[dict], market: str = "korea", source: str = "test_source",
                  currency: str = "KRW") -> pd.DataFrame:
    """Build a long-record DataFrame from minimal per-row dicts (symbol,
    date, open, high, low, close, volume, plus optional split/dividend),
    filling in market/currency/source/retrieved_at with sane defaults."""
    out = []
    for r in rows:
        row = {
            "symbol": r["symbol"], "market": r.get("market", market), "date": pd.Timestamp(r["date"]),
            "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"],
            "currency": r.get("currency", currency), "source": r.get("source", source),
            "retrieved_at": r.get("retrieved_at", pd.Timestamp("2026-08-26T00:00:00Z").isoformat()),
        }
        if "split" in r:
            row["split"] = r["split"]
        if "dividend" in r:
            row["dividend"] = r["dividend"]
        out.append(row)
    return pd.DataFrame(out)


@pytest.fixture
def clean_records():
    """10 trading days of one symbol, no issues at all (a Known-Answer
    baseline: every check should pass against this)."""
    dates = pd.bdate_range("2026-08-03", periods=8)  # Mon 08-03 .. Wed 08-12 (skips weekend)
    rows = []
    price = 10000.0
    for i, d in enumerate(dates):
        price *= 1.001
        rows.append({
            "symbol": "TEST01", "date": d.strftime("%Y-%m-%d"),
            "open": price * 0.999, "high": price * 1.002, "low": price * 0.997,
            "close": price, "volume": 100000 + i * 500,
        })
    return make_records(rows)
