"""Tests for KRDataProvider's bulk OHLCV fetching.

This sandbox has no network egress to KRX, so `pykrx` is replaced with a
fake module that records exactly which calls were made. That is the point
of these tests: the thing worth pinning down is not "does pykrx work" (it
is not ours to test) but **how many requests we issue and along which
axis** -- the naive one-request-per-symbol path is what made a real-data
Korean run take hours and get rate-limited, so a regression back to it
must fail a test rather than be discovered in production at 07:00 KST.
"""
from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from quant.data.kr_provider import KRDataProvider
from quant.utils.calendar import trading_days

# 2024-01-02 .. 2024-02-29: ~40 KRX sessions.
START, END = "2024-01-02", "2024-02-29"


def _sessions() -> pd.DatetimeIndex:
    return trading_days(START, END, "korea")


class FakePykrxStock:
    """Minimal stand-in for `pykrx.stock`, recording every call."""

    def __init__(self, equity_tickers: list[str], etf_tickers: list[str] | None = None,
                 fail_dates: set[str] | None = None):
        self.equity_tickers = equity_tickers
        self.etf_tickers = etf_tickers or []
        self.fail_dates = fail_dates or set()
        self.by_ticker_calls: list[str] = []   # one entry per (date) request
        self.by_date_calls: list[str] = []     # one entry per (symbol) request

    # by_ticker(date) -> every symbol for one session
    def get_market_ohlcv_by_ticker(self, date: str, market: str = "KOSPI"):
        self.by_ticker_calls.append(date)
        if date in self.fail_dates:
            raise RuntimeError(f"simulated KRX failure on {date}")
        return self._frame(self.equity_tickers, date)

    def get_etf_ohlcv_by_ticker(self, date: str):
        return self._frame(self.etf_tickers, date) if self.etf_tickers else pd.DataFrame()

    # by_date(ticker) -> every session for one symbol
    def get_market_ohlcv_by_date(self, fromdate: str, todate: str, ticker: str):
        self.by_date_calls.append(ticker)
        idx = pd.to_datetime([d.strftime("%Y-%m-%d") for d in _sessions()])
        base = 1000 + len(ticker)
        return pd.DataFrame(
            {"시가": base, "고가": base + 10, "저가": base - 10, "종가": base + 5, "거래량": 1_000},
            index=idx,
        )

    def get_etf_ohlcv_by_date(self, fromdate: str, todate: str, ticker: str):
        return pd.DataFrame()

    @staticmethod
    def _frame(tickers: list[str], date: str) -> pd.DataFrame:
        if not tickers:
            return pd.DataFrame()
        seed = int(date[-2:])
        return pd.DataFrame(
            {
                "시가": [1000 + seed + i for i in range(len(tickers))],
                "고가": [1010 + seed + i for i in range(len(tickers))],
                "저가": [990 + seed + i for i in range(len(tickers))],
                "종가": [1005 + seed + i for i in range(len(tickers))],
                "거래량": [10_000 + i for i in range(len(tickers))],
                "거래대금": [10_000_000 + i for i in range(len(tickers))],
            },
            index=pd.Index(tickers, name="티커"),
        )


@pytest.fixture
def fake_pykrx(monkeypatch):
    """Install a fake `pykrx` package for the duration of one test."""
    def _install(stock_obj: FakePykrxStock) -> FakePykrxStock:
        module = types.ModuleType("pykrx")
        module.stock = stock_obj
        monkeypatch.setitem(sys.modules, "pykrx", module)
        return stock_obj
    return _install


def test_many_symbols_few_sessions_fetches_by_date_not_by_symbol(fake_pykrx):
    """The universe-screen shape: thousands of names, a short window."""
    tickers = [f"{i:06d}" for i in range(300)]
    stock = fake_pykrx(FakePykrxStock(tickers))
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(tickers, START, END)

    n_sessions = len(_sessions())
    assert len(stock.by_ticker_calls) == n_sessions, "should issue one request per session"
    assert stock.by_date_calls == [], "must not fall back to per-symbol requests"
    # The whole point: request count tracks sessions, not the 300 symbols.
    assert len(stock.by_ticker_calls) < len(tickers)
    assert len(out) == len(tickers)


def test_by_date_result_has_correct_shape_and_columns(fake_pykrx):
    tickers = [f"{i:06d}" for i in range(300)]
    fake_pykrx(FakePykrxStock(tickers))
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(tickers, START, END)
    frame = out["000000"]

    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
    assert frame.index.name == "date"
    assert frame.index.is_monotonic_increasing
    assert not frame.index.has_duplicates
    assert len(frame) == len(_sessions())
    # adj_close mirrors close (KRX OHLCV is already split-adjusted).
    assert (frame["adj_close"] == frame["close"]).all()
    assert frame["high"].ge(frame["low"]).all()


def test_few_symbols_uses_per_symbol_path(fake_pykrx):
    """A handful of names over a long window: per-symbol is the cheap axis."""
    tickers = ["005930", "000660"]
    stock = fake_pykrx(FakePykrxStock([f"{i:06d}" for i in range(300)]))
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(tickers, START, END)

    assert sorted(stock.by_date_calls) == sorted(tickers)
    assert stock.by_ticker_calls == [], "must not sweep every session for 2 symbols"
    assert set(out) == set(tickers)


def test_one_failed_session_does_not_abort_the_window(fake_pykrx):
    tickers = [f"{i:06d}" for i in range(300)]
    sessions = _sessions()
    doomed = sessions[3].strftime("%Y%m%d")
    stock = fake_pykrx(FakePykrxStock(tickers, fail_dates={doomed}))
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(tickers, START, END)

    assert len(stock.by_ticker_calls) == len(sessions), "kept going past the failure"
    # Exactly the failed session is missing -- not the whole window, and not
    # silently backfilled with a neighbouring day's prices.
    assert len(out["000000"]) == len(sessions) - 1
    assert pd.Timestamp(doomed) not in out["000000"].index


def test_etf_and_equity_tickers_are_both_returned_without_duplicate_dates(fake_pykrx):
    equities = [f"{i:06d}" for i in range(200)]
    etfs = ["069500", "229200"]
    fake_pykrx(FakePykrxStock(equities, etf_tickers=etfs))
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(equities + etfs, START, END)

    assert "069500" in out and "000000" in out
    for sym in ("069500", "000000"):
        assert not out[sym].index.has_duplicates


def test_symbol_appearing_on_both_endpoints_yields_one_row_per_date(fake_pykrx):
    """A ticker listed by both the equity and ETF endpoints must not produce
    two rows for the same session -- that would fail the `duplicates`
    mandatory data-quality check and block the market for the day."""
    overlap = [f"{i:06d}" for i in range(200)]
    fake_pykrx(FakePykrxStock(overlap, etf_tickers=overlap))  # same tickers on both
    provider = KRDataProvider(request_sleep_sec=0)

    out = provider.get_ohlcv_bulk(overlap, START, END)

    frame = out["000000"]
    assert not frame.index.has_duplicates
    assert len(frame) == len(_sessions())


def test_empty_symbol_list_makes_no_requests(fake_pykrx):
    stock = fake_pykrx(FakePykrxStock([f"{i:06d}" for i in range(10)]))
    provider = KRDataProvider(request_sleep_sec=0)

    assert provider.get_ohlcv_bulk([], START, END) == {}
    assert stock.by_ticker_calls == [] and stock.by_date_calls == []


def test_duplicate_symbols_are_requested_once(fake_pykrx):
    stock = fake_pykrx(FakePykrxStock([f"{i:06d}" for i in range(300)]))
    provider = KRDataProvider(request_sleep_sec=0)

    provider.get_ohlcv_bulk(["005930", "005930", "005930"], START, END)

    assert stock.by_date_calls == ["005930"]
