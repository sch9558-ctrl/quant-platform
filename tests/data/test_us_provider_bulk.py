"""Tests for USDataProvider's bulk OHLCV fetching.

`yfinance` is replaced with a fake that records the exact arguments each
call received. The two things pinned down here are the ones that would
otherwise only show up as a red dashboard at 07:00 KST:

1. **The end date is exclusive in yfinance.** Passing `end=as_of` straight
   through drops the as_of session, which fails the mandatory `freshness`
   check (`max_lag_sessions: 0`) and Fail-Closes the US market *every*
   day. The test asserts we ask for one day past the window.
2. **Chunking.** One giant request for the whole universe is a single
   point of failure; a failing chunk must not take down the chunks that
   already succeeded.
"""
from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from quant.data.us_provider import US_BULK_CHUNK_SIZE, USDataProvider

START, END = "2024-01-02", "2024-03-01"
SESSIONS = pd.bdate_range(START, END)


def _ticker_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5,
            "Adj Close": 100.5, "Volume": 1_000_000,
        },
        index=SESSIONS,
    )


class FakeYFinance:
    def __init__(self, fail_chunks_containing: set[str] | None = None):
        self.download_calls: list[dict] = []
        self.ticker_history_calls: list[dict] = []
        self.fail_chunks_containing = fail_chunks_containing or set()

    def download(self, tickers, start=None, end=None, group_by=None,
                 auto_adjust=None, progress=None, threads=None):
        syms = list(tickers) if not isinstance(tickers, str) else [tickers]
        self.download_calls.append({"tickers": syms, "start": start, "end": end})
        if self.fail_chunks_containing & set(syms):
            raise RuntimeError("simulated yfinance failure")
        if len(syms) == 1:
            return _ticker_frame()
        frames = {s: _ticker_frame() for s in syms}
        return pd.concat(frames, axis=1)

    def Ticker(self, symbol):  # noqa: N802 -- mirrors yfinance's own casing
        outer = self

        class _T:
            def history(self, start=None, end=None, auto_adjust=None):
                outer.ticker_history_calls.append(
                    {"symbol": symbol, "start": start, "end": end})
                return _ticker_frame()

        return _T()


@pytest.fixture
def fake_yf(monkeypatch):
    def _install(obj: FakeYFinance) -> FakeYFinance:
        module = types.ModuleType("yfinance")
        module.download = obj.download
        module.Ticker = obj.Ticker
        monkeypatch.setitem(sys.modules, "yfinance", module)
        return obj
    return _install


def test_bulk_requests_one_day_past_end_so_the_as_of_session_is_included(fake_yf):
    yf = fake_yf(FakeYFinance())
    USDataProvider().get_ohlcv_bulk(["AAPL", "MSFT"], START, END)

    assert len(yf.download_calls) == 1
    requested_end = yf.download_calls[0]["end"]
    assert requested_end == "2024-03-02", (
        "yfinance's `end` is exclusive; asking for exactly as_of silently drops "
        "the as_of bar and fails the mandatory freshness check every day"
    )
    assert yf.download_calls[0]["start"] == START


def test_single_symbol_fetch_also_requests_one_day_past_end(fake_yf):
    yf = fake_yf(FakeYFinance())
    USDataProvider().get_ohlcv("AAPL", START, END)

    assert yf.ticker_history_calls[0]["end"] == "2024-03-02"


def test_large_universe_is_split_into_bounded_chunks(fake_yf):
    yf = fake_yf(FakeYFinance())
    symbols = [f"SYM{i:04d}" for i in range(US_BULK_CHUNK_SIZE * 2 + 7)]

    out = USDataProvider().get_ohlcv_bulk(symbols, START, END)

    assert len(yf.download_calls) == 3, "should be ceil(307/150) == 3 requests"
    for call in yf.download_calls:
        assert len(call["tickers"]) <= US_BULK_CHUNK_SIZE
    assert len(out) == len(symbols)


def test_one_failing_chunk_falls_back_without_losing_the_others(fake_yf):
    symbols = [f"SYM{i:04d}" for i in range(US_BULK_CHUNK_SIZE + 10)]
    doomed = symbols[0]  # lands in the first chunk
    yf = fake_yf(FakeYFinance(fail_chunks_containing={doomed}))

    out = USDataProvider().get_ohlcv_bulk(symbols, START, END)

    # Second chunk still came back from the batch path...
    assert symbols[-1] in out
    # ...and the failed chunk was recovered one symbol at a time.
    assert yf.ticker_history_calls, "expected per-symbol fallback for the bad chunk"
    assert out[doomed] is not None
    assert len(out) == len(symbols)


def test_returned_frames_have_the_canonical_shape(fake_yf):
    fake_yf(FakeYFinance())
    out = USDataProvider().get_ohlcv_bulk(["AAPL", "MSFT"], START, END)

    frame = out["AAPL"]
    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
    assert frame.index.name == "date"
    assert frame.index.tz is None, "downstream joins assume tz-naive dates"
    assert frame.index.is_monotonic_increasing


def test_duplicate_symbols_are_requested_once(fake_yf):
    yf = fake_yf(FakeYFinance())
    USDataProvider().get_ohlcv_bulk(["AAPL", "AAPL", "MSFT"], START, END)

    assert yf.download_calls[0]["tickers"] == ["AAPL", "MSFT"]


def test_empty_symbol_list_makes_no_requests(fake_yf):
    yf = fake_yf(FakeYFinance())
    assert USDataProvider().get_ohlcv_bulk([], START, END) == {}
    assert yf.download_calls == []
