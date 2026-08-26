"""Adapters between the existing wide per-symbol OHLCV format (what
`MarketDataProvider.get_ohlcv_bulk` returns, and what the feature/strategy/
backtest layers consume) and the long (symbol, market, date, ...) record
table the Data Quality Engine validates against (spec section 3).
"""
from __future__ import annotations

import pandas as pd


def to_long_records(
    ohlcv_map: dict[str, pd.DataFrame],
    market: str,
    source: str,
    currency: str,
    retrieved_at: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Flatten `{symbol: wide_ohlcv_df}` into one long table with explicit
    symbol/market/currency/source/retrieved_at columns, ready for schema,
    duplicate, missing-session, cross-source, and audit checks."""
    retrieved_at = pd.Timestamp(retrieved_at) if retrieved_at is not None else pd.Timestamp.now(tz="UTC")
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.tz_localize("UTC")

    frames = []
    for symbol, df in ohlcv_map.items():
        if df is None or df.empty:
            continue
        part = df.copy()
        part["symbol"] = symbol
        part["market"] = market
        part["currency"] = currency
        part["source"] = source
        part["retrieved_at"] = retrieved_at.isoformat()
        part["date"] = part.index
        frames.append(part.reset_index(drop=True))

    if not frames:
        cols = ["symbol", "market", "date", "open", "high", "low", "close", "volume", "currency", "source", "retrieved_at"]
        return pd.DataFrame(columns=cols)

    out = pd.concat(frames, ignore_index=True)
    return out


def to_ohlcv_map(records: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Reshape a validated long record table back into the wide
    per-symbol format the rest of the pipeline (features/strategies/
    backtester) already expects."""
    if records is None or records.empty:
        return {}

    keep_cols = [c for c in ("open", "high", "low", "close", "volume", "adj_close", "adjusted_close") if c in records.columns]
    out: dict[str, pd.DataFrame] = {}
    for symbol, group in records.groupby("symbol"):
        g = group.sort_values("date").set_index(pd.DatetimeIndex(pd.to_datetime(group["date"])))
        g = g[keep_cols].copy()
        if "adjusted_close" in g.columns and "adj_close" not in g.columns:
            g = g.rename(columns={"adjusted_close": "adj_close"})
        out[symbol] = g
    return out
