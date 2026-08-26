"""US Secondary Provider (spec section 9): an independent second data
source used only to cross-validate the Primary provider (`us_provider.py`,
yfinance), never to build a universe or drive a strategy on its own.

Backed directly by Stooq's public CSV export (stooq.com/q/d/l/), fetched
with a plain `requests` GET rather than a wrapper library --
`pandas-datareader`'s built-in Stooq reader was removed in recent releases
upstream, and the endpoint itself is simple enough not to need one.

SANDBOX NETWORK NOTE: like `us_provider.py`, this is code-complete but has
not been exercised against a live network from this development
environment (this sandbox can reach pypi.org but not stooq.com -- see
README.md "Running with real data"). Validate on a machine with normal
internet access before relying on it.
"""
from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

from quant.utils.logging import get_logger

logger = get_logger(__name__)

_STOOQ_URL = "https://stooq.com/q/d/l/"
_TIMEOUT_SECONDS = 15


class USSecondaryProvider:
    """Minimal secondary-source interface (`get_ohlcv` / `get_ohlcv_bulk`)
    -- see `SyntheticSecondaryProvider`'s docstring for why this
    deliberately does not implement the full `MarketDataProvider` ABC."""

    market = "us"

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])
        try:
            resp = requests.get(
                _STOOQ_URL,
                params={"s": symbol.lower(), "d1": pd.Timestamp(start).strftime("%Y%m%d"),
                        "d2": pd.Timestamp(end).strftime("%Y%m%d"), "i": "d"},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("USSecondaryProvider.get_ohlcv failed for %s: %s", symbol, e)
            return empty

        text = resp.text.strip()
        if not text or text.startswith("No data") or "," not in text.splitlines()[0]:
            return empty

        try:
            raw = pd.read_csv(StringIO(text))
        except Exception as e:
            logger.warning("USSecondaryProvider: could not parse Stooq CSV for %s: %s", symbol, e)
            return empty

        if raw.empty or "Date" not in raw.columns:
            return empty

        raw["Date"] = pd.to_datetime(raw["Date"])
        raw = raw.set_index("Date").rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
        })
        raw.index.name = "date"
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in raw.columns]
        out = raw[keep].copy()
        out["adj_close"] = out["close"]  # Stooq's free daily series is close-price only, not separately adjusted
        return out

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        out = {}
        for sym in symbols:
            df = self.get_ohlcv(sym, start, end)
            if df is not None and not df.empty:
                out[sym] = df
        return out
