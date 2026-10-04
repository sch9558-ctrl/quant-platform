"""US Secondary Provider (spec section 9): an independent second data
source used only to cross-validate the Primary provider (`us_provider.py`,
yfinance), never to build a universe or drive a strategy on its own.

Backed directly by Stooq's public CSV export (stooq.com/q/d/l/), fetched
with a plain `requests` GET rather than a wrapper library --
`pandas-datareader`'s built-in Stooq reader was removed in recent releases
upstream, and the endpoint itself is simple enough not to need one.

TWO FAILURES THIS MODULE SHIPPED WITH, both found in CI on 2026-09-30:

1. **Every US request 404'd.** Stooq namespaces symbols by exchange
   country: `AAL` is `aal.us`, not `aal`. Without the suffix the endpoint
   answers 404 for every US ticker, so cross-source validation for the US
   market had never once run -- and it failed *quietly*, because an empty
   secondary is a legitimate, expected state (`cross_source.require_secondary`
   is false, and the check is then reported SKIPPED rather than passed).
   A check that silently never runs is worse than one that fails: the
   report looked reasonable the whole time.

2. **Failing took two and a half hours.** After a few hundred 404s Stooq
   began refusing connections outright, and each of the remaining symbols
   burned the full connect timeout. 400 symbols later the job hit the
   runner's wall clock and was cancelled, so the *entire* pipeline produced
   nothing -- killed by its own optional cross-check.

So this module now (a) sends the symbol Stooq actually expects and (b)
gives up on itself. A secondary source is a nice-to-have; it is never
worth the run. `get_ohlcv_bulk` abandons the source for the rest of the
call after a run of consecutive failures or once its time budget is spent,
and says so loudly. The caller then sees the same empty result it already
knows how to report honestly as SKIPPED.
"""
from __future__ import annotations

import os
import time
from io import StringIO

import pandas as pd
import requests

from quant.utils.logging import get_logger

logger = get_logger(__name__)

_STOOQ_URL = "https://stooq.com/q/d/l/"

#: Per-request timeout. Deliberately short: this source is optional, and a
#: slow answer costs the pipeline more than a missing one.
_TIMEOUT_SECONDS = 4.0

#: Consecutive failures after which the source is considered unavailable
#: for the rest of this bulk call. Stooq answers healthy symbols quickly,
#: so a run this long means the endpoint is refusing us, not that these
#: particular tickers are unusual.
_MAX_CONSECUTIVE_FAILURES = 3

#: Total wall clock a bulk call may spend. The circuit breaker above
#: handles an outright block; this bounds the slower pathology where
#: roughly half the requests time out and the run never quite trips it.
_BULK_TIME_BUDGET_SECONDS = 60.0


def to_stooq_symbol(symbol: str) -> str:
    """Translate a US ticker into the symbol Stooq serves it under.

    Stooq keys US listings with a `.us` country suffix and uses `-` where
    US feeds use a class separator: `BRK.B` is `brk-b.us`. Symbols that
    already carry a country suffix are passed through so a caller can
    request a non-US listing deliberately.
    """
    s = symbol.strip().lower()
    if not s:
        return s
    if "." in s:
        head, _, tail = s.rpartition(".")
        # `aal.us` -> already suffixed; `brk.b` -> class share
        if len(tail) == 2 and tail.isalpha() and head:
            return s
        s = s.replace(".", "-")
    s = s.replace("$", "-")
    return f"{s}.us"


class USSecondaryProvider:
    """Minimal secondary-source interface (`get_ohlcv` / `get_ohlcv_bulk`)
    -- see `SyntheticSecondaryProvider`'s docstring for why this
    deliberately does not implement the full `MarketDataProvider` ABC."""

    market = "us"

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or os.getenv("STOOQ_API_KEY", "")).strip()

    @staticmethod
    def _empty() -> pd.DataFrame:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        empty = self._empty()
        try:
            params = {
                "s": to_stooq_symbol(symbol),
                "d1": pd.Timestamp(start).strftime("%Y%m%d"),
                "d2": pd.Timestamp(end).strftime("%Y%m%d"),
                "i": "d",
            }
            if self.api_key:
                params["apikey"] = self.api_key
            resp = requests.get(
                _STOOQ_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 quant-platform research"},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("USSecondaryProvider.get_ohlcv failed for %s: %s", symbol, e)
            return empty

        text = resp.text.strip()
        lower = text.lower()
        if (
            not text
            or text.startswith("No data")
            or "get your apikey" in lower
            or "exceeded the daily hits limit" in lower
            or "," not in text.splitlines()[0]
        ):
            logger.warning(
                "USSecondaryProvider: Stooq returned a non-CSV contract response for %s%s",
                symbol,
                " (STOOQ_API_KEY is not configured)" if not self.api_key else "",
            )
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
        """Fetch what this source can, and stop when it clearly cannot.

        Returning early leaves the cross-source check with no secondary
        data, which the quality engine already reports as SKIPPED rather
        than as two sources agreeing. That is the honest outcome, and it
        costs minutes instead of the whole run.
        """
        out: dict[str, pd.DataFrame] = {}
        consecutive_failures = 0
        started = time.monotonic()

        for i, sym in enumerate(symbols):
            elapsed = time.monotonic() - started
            if elapsed > _BULK_TIME_BUDGET_SECONDS:
                logger.warning(
                    "USSecondaryProvider: giving up after %.0fs (%d/%d symbols, %d usable). "
                    "Cross-source validation will be reported as SKIPPED for this run rather "
                    "than spending the pipeline's remaining time on an optional check.",
                    elapsed, i, len(symbols), len(out),
                )
                break

            df = self.get_ohlcv(sym, start, end)
            if df is not None and not df.empty:
                out[sym] = df
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "USSecondaryProvider: %d consecutive failures ending at %s -- treating Stooq "
                    "as unavailable for this run and stopping after %d/%d symbols (%d usable). "
                    "This is the source refusing us, not these tickers being unusual.",
                    consecutive_failures, sym, i + 1, len(symbols), len(out),
                )
                break

        return out
