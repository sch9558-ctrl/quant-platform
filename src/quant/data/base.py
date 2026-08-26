"""Abstract market data provider interface.

Every concrete provider (KR/US, real or synthetic) implements this interface,
so nothing downstream (universe/features/strategy/backtest) needs to know or
care where the bytes actually came from. This is what lets the whole research
pipeline be developed and unit-tested against a `SyntheticDataProvider` and
later pointed at real `KRDataProvider` / `USDataProvider` with zero changes
elsewhere.

All OHLCV frames returned by any provider follow the same contract:
  - DatetimeIndex named "date", sorted ascending, one row per trading day
  - columns: open, high, low, close, volume, adj_close
  - prices are in the market's native currency (KRW for Korea, USD for US)
  - no look-ahead: a frame for `end` date never contains information that
    would not have been publicly known by the close of `end`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume", "adj_close"]


@dataclass
class SymbolInfo:
    symbol: str
    name: str
    market: str          # "korea" | "us"
    exchange: str         # "KOSPI" | "KOSDAQ" | "NYSE" | "NASDAQ" | "AMEX"
    asset_type: str = "equity"   # "equity" | "etf"
    sector: str | None = None
    listing_date: pd.Timestamp | None = None
    is_active: bool = True
    is_administrative: bool = False  # 관리종목
    is_trading_halted: bool = False


@dataclass
class FundamentalSnapshot:
    symbol: str
    as_of: pd.Timestamp
    per: float | None = None
    pbr: float | None = None
    roe: float | None = None
    eps: float | None = None
    eps_growth: float | None = None
    revenue_growth: float | None = None
    operating_margin: float | None = None
    debt_ratio: float | None = None
    dividend_yield: float | None = None
    market_cap: float | None = None
    extra: dict = field(default_factory=dict)


class MarketDataProvider(ABC):
    """Abstract base for all market data sources."""

    market: str  # "korea" | "us"

    @abstractmethod
    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        """Return the full listed-symbol universe (pre any research filters)."""

    @abstractmethod
    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Return OHLCV history for one symbol, columns = OHLCV_COLUMNS."""

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        """Default naive implementation; providers may override for batching."""
        out = {}
        for sym in symbols:
            try:
                df = self.get_ohlcv(sym, start, end)
            except Exception:
                continue
            if df is not None and not df.empty:
                out[sym] = df
        return out

    @abstractmethod
    def get_market_cap(self, symbols: list[str], as_of: str) -> pd.Series:
        """Return market cap (native currency) as of a date, indexed by symbol."""

    @abstractmethod
    def get_fundamentals(self, symbols: list[str], as_of: str) -> pd.DataFrame:
        """Return a fundamentals snapshot frame indexed by symbol."""

    @abstractmethod
    def get_index_ohlcv(self, index_symbol: str, start: str, end: str) -> pd.DataFrame:
        """Return OHLCV for a benchmark/reference index."""
