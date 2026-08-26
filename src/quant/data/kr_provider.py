"""Korea market data provider backed by `pykrx` (scrapes public KRX data,
no API key required).

NOTE ON THIS SANDBOX: the cloud workspace this was developed in does not
have network egress to KRX's servers, so this module could not be exercised
against live data during development (see README.md -> "Running with real
data"). The implementation follows pykrx's documented public API closely and
is defensively coded (retries are left to the caller / cache layer), but you
should run `pytest tests/data/test_kr_provider_smoke.py -m network` once on
a machine with normal internet access to confirm end-to-end before relying
on it for research.
"""
from __future__ import annotations

import time

import pandas as pd

from quant.data.base import FundamentalSnapshot, MarketDataProvider, SymbolInfo
from quant.utils.logging import get_logger

logger = get_logger(__name__)

_KR_COL_MAP = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
    "거래대금": "trading_value",
    "등락률": "pct_change",
}

INDEX_TICKERS = {
    "KOSPI": "1001",
    "KOSDAQ": "2001",
    "KOSPI200": "1028",
}


class KRDataProvider(MarketDataProvider):
    market = "korea"

    def __init__(self, request_sleep_sec: float = 0.05):
        self._request_sleep_sec = request_sleep_sec

    # -- internal -------------------------------------------------------
    def _sleep(self):
        if self._request_sleep_sec:
            time.sleep(self._request_sleep_sec)

    @staticmethod
    def _fmt(d: str) -> str:
        """pykrx wants YYYYMMDD strings."""
        return pd.Timestamp(d).strftime("%Y%m%d")

    # -- MarketDataProvider interface -----------------------------------
    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        from pykrx import stock

        as_of = as_of or pd.Timestamp.today().strftime("%Y-%m-%d")
        date_str = self._fmt(as_of)
        out: list[SymbolInfo] = []

        for market_name in ("KOSPI", "KOSDAQ"):
            tickers = stock.get_market_ticker_list(date_str, market=market_name)
            for t in tickers:
                try:
                    name = stock.get_market_ticker_name(t)
                except Exception:
                    name = t
                out.append(SymbolInfo(
                    symbol=t, name=name, market="korea", exchange=market_name,
                    asset_type="equity",
                ))
            self._sleep()

        for t in stock.get_etf_ticker_list(date_str):
            try:
                name = stock.get_etf_ticker_name(t)
            except Exception:
                name = t
            out.append(SymbolInfo(
                symbol=t, name=name, market="korea", exchange="KOSPI",
                asset_type="etf",
            ))

        return out

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        from pykrx import stock

        fromdate, todate = self._fmt(start), self._fmt(end)
        try:
            df = stock.get_market_ohlcv_by_date(fromdate, todate, symbol)
            if df is None or df.empty:
                # fall back to ETF endpoint
                df = stock.get_etf_ohlcv_by_date(fromdate, todate, symbol)
        except Exception as e:
            logger.warning("KR OHLCV fetch failed for %s: %s", symbol, e)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])

        df = df.rename(columns=_KR_COL_MAP)
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep].copy()
        df["adj_close"] = df["close"]  # pykrx OHLCV is already split-adjusted by KRX convention
        df.index.name = "date"
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def get_market_cap(self, symbols: list[str], as_of: str) -> pd.Series:
        from pykrx import stock

        date_str = self._fmt(as_of)
        caps: dict[str, float] = {}
        for market_name in ("KOSPI", "KOSDAQ"):
            try:
                df = stock.get_market_cap_by_ticker(date_str, market=market_name)
            except Exception as e:
                logger.warning("KR market cap fetch failed for %s on %s: %s", market_name, date_str, e)
                continue
            if df is None or df.empty:
                continue
            col = "시가총액" if "시가총액" in df.columns else df.columns[0]
            for sym in symbols:
                if sym in df.index:
                    caps[sym] = float(df.loc[sym, col])
        return pd.Series(caps, name="market_cap")

    def get_fundamentals(self, symbols: list[str], as_of: str) -> pd.DataFrame:
        from pykrx import stock

        date_str = self._fmt(as_of)
        rows: list[FundamentalSnapshot] = []
        for market_name in ("KOSPI", "KOSDAQ"):
            try:
                df = stock.get_market_fundamental_by_ticker(date_str, market=market_name)
            except Exception as e:
                logger.warning("KR fundamentals fetch failed for %s on %s: %s", market_name, date_str, e)
                continue
            if df is None or df.empty:
                continue
            for sym in symbols:
                if sym not in df.index:
                    continue
                row = df.loc[sym]
                rows.append(FundamentalSnapshot(
                    symbol=sym,
                    as_of=pd.Timestamp(as_of),
                    per=row.get("PER"),
                    pbr=row.get("PBR"),
                    eps=row.get("EPS"),
                    dividend_yield=row.get("DIV"),
                    extra={"BPS": row.get("BPS"), "DPS": row.get("DPS")},
                ))
        if not rows:
            return pd.DataFrame()
        df_out = pd.DataFrame([vars(r) for r in rows]).set_index("symbol")
        return df_out

    def get_index_ohlcv(self, index_symbol: str, start: str, end: str) -> pd.DataFrame:
        from pykrx import stock

        ticker = INDEX_TICKERS.get(index_symbol.upper(), index_symbol)
        fromdate, todate = self._fmt(start), self._fmt(end)
        df = stock.get_index_ohlcv_by_date(fromdate, todate, ticker)
        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])
        df = df.rename(columns=_KR_COL_MAP)
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[keep].copy()
        df["adj_close"] = df["close"]
        df.index.name = "date"
        df.index = pd.to_datetime(df.index)
        return df.sort_index()
