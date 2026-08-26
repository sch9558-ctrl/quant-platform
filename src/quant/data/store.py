"""Local read-through cache for OHLCV and reference data.

Real data providers (KR/US) hit the network, which is comparatively slow and
rate-limited. This module caches per-symbol OHLCV history as parquet files
under `data/cache/<market>/<symbol>.parquet`, and refreshes only when the
*requested* range extends beyond what has previously been fetched.

Coverage is tracked via an explicit sidecar "fetch range" (the min/max dates
ever *requested* and fetched for a symbol), not by the min/max dates that
happen to appear in the cached data. This distinction matters because a
young symbol may have been listed after the requested start date -- in that
case the data legitimately starts later than the request, and that is not a
cache miss, just "no data exists before listing." Using the data's own
min/max as the coverage signal would cause every such symbol to be re-fetched
on every call.

This is also where "point-in-time" discipline starts: cached frames are
never mutated to reflect information that arrives later (e.g. a corporate
action discovered after the fact gets appended as new rows / a new
`fetched_at` snapshot, not silently rewritten into history), which keeps the
research pipeline honest about look-ahead bias.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant import config


class ParquetCache:
    def __init__(self, market: str, base_dir: Path | None = None):
        self.market = market
        base = base_dir or config.resolve_path(config.settings()["paths"]["data_cache"])
        self.dir = Path(base) / market
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        safe = symbol.replace("/", "_").replace("^", "IDX_")
        return self.dir / f"{safe}.parquet"

    def _meta_path(self, symbol: str) -> Path:
        safe = symbol.replace("/", "_").replace("^", "IDX_")
        return self.dir / f"{safe}.meta.json"

    def load(self, symbol: str) -> pd.DataFrame | None:
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            return pd.read_parquet(p)
        except Exception:
            return None

    def save(self, symbol: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.to_parquet(self._path(symbol))

    def upsert(self, symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
        existing = self.load(symbol)
        if existing is None or existing.empty:
            merged = new_df
        else:
            merged = pd.concat([existing, new_df])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        self.save(symbol, merged)
        return merged

    def get_fetch_range(self, symbol: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """The min/max of every date range ever *requested and fetched* for
        this symbol (not the min/max of actual data rows -- see module
        docstring)."""
        p = self._meta_path(symbol)
        if not p.exists():
            return None
        try:
            meta = json.loads(p.read_text())
            return pd.Timestamp(meta["fetch_start"]), pd.Timestamp(meta["fetch_end"])
        except Exception:
            return None

    def update_fetch_range(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> None:
        existing = self.get_fetch_range(symbol)
        if existing is not None:
            start = min(start, existing[0])
            end = max(end, existing[1])
        self._meta_path(symbol).write_text(json.dumps({
            "fetch_start": start.strftime("%Y-%m-%d"),
            "fetch_end": end.strftime("%Y-%m-%d"),
        }))

    def coverage(self, symbol: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """Actual data extent (for diagnostics), distinct from fetch range."""
        df = self.load(symbol)
        if df is None or df.empty:
            return None
        return df.index.min(), df.index.max()


def cached_get_ohlcv(provider, cache: ParquetCache, symbol: str, start: str, end: str) -> pd.DataFrame:
    """Read-through cache wrapper around any provider.get_ohlcv()."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    fetch_range = cache.get_fetch_range(symbol)

    already_covered = (
        fetch_range is not None
        and fetch_range[0] <= start_ts
        and fetch_range[1] >= end_ts
    )

    if already_covered:
        cached = cache.load(symbol)
        if cached is not None:
            return cached.loc[start_ts:end_ts]
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

    fresh = provider.get_ohlcv(symbol, start, end)
    cache.update_fetch_range(symbol, start_ts, end_ts)

    if fresh is None or fresh.empty:
        cached = cache.load(symbol)
        return cached.loc[start_ts:end_ts] if cached is not None else pd.DataFrame(columns=[
            "open", "high", "low", "close", "volume", "adj_close"
        ])
    merged = cache.upsert(symbol, fresh)
    return merged.loc[start_ts:end_ts]
