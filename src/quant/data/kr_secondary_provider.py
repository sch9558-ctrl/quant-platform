"""Korea Secondary Provider (spec section 9): an independent second data
source used only to cross-validate the Primary provider (`kr_provider.py`,
pykrx), never to build a universe or drive a strategy on its own.

Backed by `FinanceDataReader` (github.com/FinanceData/FinanceDataReader),
which itself pulls from KRX/Naver Finance -- a different code path and
maintainer than `pykrx`, which is the point of having it as a second,
independent check rather than a second call to the same underlying source.

SANDBOX NETWORK NOTE: like `kr_provider.py`, this is code-complete but has
not been exercised against a live network from this development
environment (see README.md "Running with real data"). Validate on a
machine with normal internet access before relying on it.
"""
from __future__ import annotations

import pandas as pd

from quant.utils.logging import get_logger

logger = get_logger(__name__)


class KRSecondaryProvider:
    """Minimal secondary-source interface (`get_ohlcv` / `get_ohlcv_bulk`)
    -- see `SyntheticSecondaryProvider`'s docstring for why this
    deliberately does not implement the full `MarketDataProvider` ABC."""

    market = "korea"

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            import FinanceDataReader as fdr
        except ImportError as e:  # pragma: no cover - environment-dependent
            logger.warning("FinanceDataReader not installed: %s", e)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        try:
            raw = fdr.DataReader(symbol, start, end)
        except Exception as e:
            logger.warning("KRSecondaryProvider.get_ohlcv failed for %s: %s", symbol, e)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        if raw is None or raw.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        out = raw.rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
        })
        out.index.name = "date"
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in out.columns]
        out = out[keep].copy()
        out["adj_close"] = out["close"]  # FinanceDataReader's KRX series is already split/dividend-adjusted
        return out.loc[pd.Timestamp(start):pd.Timestamp(end)]

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        out = {}
        for sym in symbols:
            df = self.get_ohlcv(sym, start, end)
            if df is not None and not df.empty:
                out[sym] = df
        return out
