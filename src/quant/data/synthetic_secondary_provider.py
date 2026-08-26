"""A deterministic "second data source" for demo/offline testing of the
Data Quality Engine's Cross-Source Validation (spec sections 9-11).

This is NOT a second real vendor -- it exists purely so the multi-source
comparison and canonical-consensus code paths can be exercised end-to-end
in this sandbox (which has no network access to real secondary vendors;
see `kr_secondary_provider.py` / `us_secondary_provider.py` for the
code-complete real implementations). It wraps an existing
`SyntheticDataProvider` and applies a small, stable (hash-seeded, not
`hash()`-per-process-random -- see `synthetic_provider.py`'s own
reproducibility note) multiplicative perturbation to each OHLCV value, so
the two "sources" mostly agree (as two real vendors usually do) while
still being numerically distinct -- a real comparison, not a tautology.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from quant.data.synthetic_provider import SyntheticDataProvider

_DEFAULT_NOISE_PCT = 0.05  # 0.05% typical vendor-to-vendor rounding/timing noise


def _stable_noise(symbol: str, date: pd.Timestamp, noise_pct: float) -> float:
    key = f"{symbol}|{date.strftime('%Y-%m-%d')}"
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    # map to [-noise_pct, +noise_pct] deterministically
    unit = (h % 20000) / 10000.0 - 1.0  # in [-1, 1]
    return unit * (noise_pct / 100.0)


class SyntheticSecondaryProvider:
    """Minimal secondary-source interface: only what the Data Quality
    Engine's cross-source comparison needs (`get_ohlcv_bulk`), not the
    full `MarketDataProvider` ABC -- a secondary/reference source is
    consulted for comparison, never used on its own to build a universe or
    drive a strategy."""

    def __init__(self, primary: SyntheticDataProvider, noise_pct: float = _DEFAULT_NOISE_PCT):
        self._primary = primary
        self._noise_pct = noise_pct

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        df = self._primary.get_ohlcv(symbol, start, end)
        if df is None or df.empty:
            return df
        out = df.copy()
        noise = np.array([_stable_noise(symbol, d, self._noise_pct) for d in df.index])
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = out[col] * (1 + noise)
        return out

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        out = {}
        for sym in symbols:
            df = self.get_ohlcv(sym, start, end)
            if df is not None and not df.empty:
                out[sym] = df
        return out
