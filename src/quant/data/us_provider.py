"""US market data provider backed by `yfinance` (no API key required).

Universe discovery ("all listed symbols") uses NASDAQ Trader's public
symbol-directory files, which is the standard free, no-auth source for a
full NYSE/NASDAQ/AMEX ticker list:
  https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
  https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt
No ticker is hardcoded in this file; index constituents (S&P 500,
NASDAQ-100) are handled separately in `quant.universe.us_constituents`.

NOTE ON THIS SANDBOX: like kr_provider.py, this could not be exercised
against live network during development here (see README.md -> "Running
with real data"). Validate on a machine with normal internet access before
relying on it.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from quant.data.base import MarketDataProvider, SymbolInfo
from quant.utils.logging import get_logger

logger = get_logger(__name__)

#: How many tickers to ask yfinance for per `download()` call. Large enough
#: that the universe is a handful of requests, small enough that one failure
#: costs one chunk rather than the whole market.
US_BULK_CHUNK_SIZE = 150

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

INDEX_TICKERS = {
    "SP500": "^GSPC",
    "NASDAQ100": "^NDX",
    "DOWJONES": "^DJI",
    "RUSSELL2000": "^RUT",
}

_EXCHANGE_CODE_MAP = {  # otherlisted.txt "Exchange" column codes
    "A": "AMEX",
    "N": "NYSE",
    "P": "NYSE",   # NYSE Arca
    "Z": "AMEX",   # BATS/Cboe BZX, treated as AMEX-tier venue for our purposes
    "V": "NASDAQ",
}


class USDataProvider(MarketDataProvider):
    market = "us"

    def __init__(self, timeout: int = 15):
        self._timeout = timeout

    # -- MarketDataProvider interface -----------------------------------
    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        """Full NYSE/NASDAQ/AMEX common-stock + ETF universe via NASDAQ Trader
        symbol directory files. Falls back to an empty list (with a logged
        warning) if the endpoint is unreachable -- callers should then rely
        on index-based universes (S&P 500 / NASDAQ-100 / major ETFs) via
        `quant.universe.us_constituents` instead.
        """
        out: list[SymbolInfo] = []

        try:
            nasdaq_df = self._fetch_symbol_directory(NASDAQ_LISTED_URL)
            for _, row in nasdaq_df.iterrows():
                if str(row.get("Test Issue", "N")).strip() == "Y":
                    continue
                sym = str(row["Symbol"]).strip()
                is_etf = str(row.get("ETF", "N")).strip() == "Y"
                out.append(SymbolInfo(
                    symbol=sym, name=str(row.get("Security Name", sym)),
                    market="us", exchange="NASDAQ",
                    asset_type="etf" if is_etf else "equity",
                ))
        except Exception as e:
            logger.warning("Failed to fetch NASDAQ symbol directory: %s", e)

        try:
            other_df = self._fetch_symbol_directory(OTHER_LISTED_URL)
            for _, row in other_df.iterrows():
                if str(row.get("Test Issue", "N")).strip() == "Y":
                    continue
                sym = str(row.get("ACT Symbol", row.get("Symbol", ""))).strip()
                if not sym:
                    continue
                exch_code = str(row.get("Exchange", "")).strip()
                exchange = _EXCHANGE_CODE_MAP.get(exch_code, "NYSE")
                is_etf = str(row.get("ETF", "N")).strip() == "Y"
                out.append(SymbolInfo(
                    symbol=sym, name=str(row.get("Security Name", sym)),
                    market="us", exchange=exchange,
                    asset_type="etf" if is_etf else "equity",
                ))
        except Exception as e:
            logger.warning("Failed to fetch other-listed symbol directory: %s", e)

        return out

    @staticmethod
    def _fetch_symbol_directory(url: str) -> pd.DataFrame:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        text = resp.text
        # last line is typically a "File Creation Time" footer; drop it
        lines = [l for l in text.splitlines() if l and not l.startswith("File Creation Time")]
        return pd.read_csv(io.StringIO("\n".join(lines)), sep="|")

    @staticmethod
    def _yf_end(end: str) -> str:
        """yfinance treats `end` as EXCLUSIVE.

        Passing `end=as_of` straight through therefore silently drops the
        as_of session itself. That is not a cosmetic off-by-one: `freshness`
        is a mandatory data-quality check configured with
        `max_lag_sessions: 0`, so a permanently-missing final bar would fail
        it every single day and Fail-Closed the US market every morning --
        with a report blaming the data provider rather than this line. Ask
        for one day past the window so the requested end date is included.
        """
        return (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        import yfinance as yf

        try:
            df = yf.Ticker(symbol).history(start=start, end=self._yf_end(end), auto_adjust=False)
        except Exception as e:
            logger.warning("US OHLCV fetch failed for %s: %s", symbol, e)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close",
            "Volume": "volume", "Adj Close": "adj_close",
        })
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]
        df = df[["open", "high", "low", "close", "volume", "adj_close"]]
        df.index.name = "date"
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.sort_index()

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        """Batch-download OHLCV, in chunks.

        yfinance can take many tickers per call, but one call carrying the
        whole universe (hundreds of names) is a single point of failure: it
        builds a very long request, is slow enough to hit timeouts, and when
        anything goes wrong the entire universe comes back empty rather than
        just the affected names. Chunking bounds that blast radius -- a bad
        chunk falls back to per-symbol fetching on its own without dragging
        down the chunks that already succeeded.
        """
        symbols = list(dict.fromkeys(symbols))  # de-dupe, preserve order
        if not symbols:
            return {}

        out: dict[str, pd.DataFrame] = {}
        for i in range(0, len(symbols), US_BULK_CHUNK_SIZE):
            chunk = symbols[i:i + US_BULK_CHUNK_SIZE]
            out.update(self._download_chunk(chunk, start, end))
        return out

    def _download_chunk(self, chunk: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        try:
            raw = yf.download(chunk, start=start, end=self._yf_end(end), group_by="ticker",
                              auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            logger.warning("US bulk OHLCV download failed for a %d-symbol chunk, "
                           "falling back to per-symbol: %s", len(chunk), e)
            return super().get_ohlcv_bulk(chunk, start, end)

        if raw is None or raw.empty:
            return {}

        out: dict[str, pd.DataFrame] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            available = set(raw.columns.get_level_values(0))
            for sym in chunk:
                if sym not in available:
                    continue
                frame = self._normalize(raw[sym].dropna(how="all"))
                if frame is not None:
                    out[sym] = frame
        else:
            # yfinance collapses the ticker level when a chunk has one symbol
            frame = self._normalize(raw)
            if frame is not None:
                out[chunk[0]] = frame
        return out

    @staticmethod
    def _normalize(sub: pd.DataFrame) -> pd.DataFrame | None:
        if sub is None or sub.empty:
            return None
        sub = sub.rename(columns={
            "Open": "open", "High": "high", "Low": "low", "Close": "close",
            "Volume": "volume", "Adj Close": "adj_close",
        })
        if not {"open", "high", "low", "close", "volume"}.issubset(sub.columns):
            return None
        if "adj_close" not in sub.columns:
            sub["adj_close"] = sub["close"]
        sub = sub[["open", "high", "low", "close", "volume", "adj_close"]].copy()
        sub.index.name = "date"
        sub.index = pd.to_datetime(sub.index).tz_localize(None)
        return sub.sort_index()

    def get_market_cap(self, symbols: list[str], as_of: str) -> pd.Series:
        import yfinance as yf

        caps: dict[str, float] = {}
        for sym in symbols:
            try:
                info = yf.Ticker(sym).fast_info
                cap = getattr(info, "market_cap", None) or info.get("marketCap")
                if cap:
                    caps[sym] = float(cap)
            except Exception as e:
                logger.debug("US market cap fetch failed for %s: %s", sym, e)
        return pd.Series(caps, name="market_cap")

    def get_fundamentals(self, symbols: list[str], as_of: str) -> pd.DataFrame:
        import yfinance as yf

        rows = []
        for sym in symbols:
            try:
                info = yf.Ticker(sym).get_info()
            except Exception as e:
                logger.debug("US fundamentals fetch failed for %s: %s", sym, e)
                continue
            rows.append({
                "symbol": sym,
                "per": info.get("trailingPE"),
                "pbr": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "eps": info.get("trailingEps"),
                "eps_growth": info.get("earningsGrowth"),
                "revenue_growth": info.get("revenueGrowth"),
                "operating_margin": info.get("operatingMargins"),
                "debt_ratio": info.get("debtToEquity"),
                "dividend_yield": info.get("dividendYield"),
                "market_cap": info.get("marketCap"),
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("symbol")

    def get_index_ohlcv(self, index_symbol: str, start: str, end: str) -> pd.DataFrame:
        ticker = INDEX_TICKERS.get(index_symbol.upper(), index_symbol)
        return self.get_ohlcv(ticker, start, end)
