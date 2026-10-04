"""The US secondary source must ask for the right symbol, and must give up.

Both properties come from the same CI run (2026-09-30), where this one
optional check consumed the entire pipeline:

* every request 404'd, because Stooq serves US listings as `aal.us` and we
  were asking for `aal`. Cross-source validation for the US market had
  therefore never run at all -- and it failed silently, because an absent
  secondary is a legitimate state the engine reports as SKIPPED;
* then Stooq started refusing connections, and the remaining ~300 symbols
  each burned the full connect timeout until the job hit the runner's
  2h30m ceiling and was cancelled. The pipeline produced nothing.

These are fast, offline tests: `requests.get` is replaced, so they pin the
request we *send* and the decision to *stop*, which is exactly what went
wrong. They cannot tell us Stooq's schema changed -- only a live run can.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quant.data import us_secondary_provider as mod
from quant.data.us_secondary_provider import USSecondaryProvider, to_stooq_symbol

CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-09-28,10.0,11.0,9.5,10.5,1000\n"
    "2026-09-29,10.5,11.5,10.0,11.0,1200\n"
)


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"{self.status} Client Error")


# -- the symbol we send ------------------------------------------------

@pytest.mark.parametrize(
    "ticker, expected",
    [
        ("AAL", "aal.us"),
        ("aal", "aal.us"),
        ("  MSFT  ", "msft.us"),
        ("BRK.B", "brk-b.us"),      # class share: dot becomes a dash
        ("BF.A", "bf-a.us"),
        ("AAL.US", "aal.us"),        # already suffixed -> unchanged
        ("PBR.SA", "pbr.sa"),        # a deliberate non-US listing is respected
    ],
)
def test_symbols_are_translated_to_stooqs_namespace(ticker, expected):
    assert to_stooq_symbol(ticker) == expected


def test_the_request_actually_carries_the_suffixed_symbol(monkeypatch):
    """The bug was one missing suffix, so pin the wire format, not the
    helper -- the helper was never the thing that talked to Stooq."""
    sent = {}

    def fake_get(url, params=None, timeout=None, **kwargs):
        sent.update(params or {})
        sent["url"] = url
        sent["timeout"] = timeout
        return _Resp(CSV)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    USSecondaryProvider(api_key="fixture-key").get_ohlcv("AAL", "2026-09-01", "2026-09-29")

    assert sent["s"] == "aal.us", "a bare ticker is a 404 on every US symbol"
    assert sent["apikey"] == "fixture-key", "2026 Stooq CSV contract requires an API key"
    assert sent["d1"] == "20260901" and sent["d2"] == "20260929"
    assert sent["timeout"] is not None, "an optional source must never hang unbounded"


def test_a_successful_response_is_parsed_into_the_standard_frame(monkeypatch):
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp(CSV))
    df = USSecondaryProvider().get_ohlcv("AAL", "2026-09-01", "2026-09-29")
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == 11.0
    assert (df["adj_close"] == df["close"]).all()


# -- giving up -----------------------------------------------------------

def test_bulk_stops_after_a_run_of_consecutive_failures(monkeypatch):
    """The source refusing us looks like failure after failure. Continuing
    to ask 400 times is what cost the run."""
    calls = []

    def fake_get(url, params=None, timeout=None, **kwargs):
        calls.append(params["s"])
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(mod.requests, "get", fake_get)
    symbols = [f"SYM{i}" for i in range(400)]
    out = USSecondaryProvider().get_ohlcv_bulk(symbols, "2026-09-01", "2026-09-29")

    assert out == {}
    assert len(calls) <= mod._MAX_CONSECUTIVE_FAILURES, (
        f"asked {len(calls)} times after the source stopped answering; the whole "
        "point of the breaker is that an optional check cannot eat the pipeline"
    )


def test_an_isolated_failure_does_not_trip_the_breaker(monkeypatch):
    """A delisted or unusual ticker is normal and must not abandon the
    source -- otherwise the breaker would make cross-validation useless."""
    def fake_get(url, params=None, timeout=None, **kwargs):
        if params["s"].startswith("bad"):
            raise RuntimeError("404")
        return _Resp(CSV)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    symbols = []
    for i in range(30):
        symbols.append(f"BAD{i}" if i % 5 == 0 else f"OK{i}")

    out = USSecondaryProvider().get_ohlcv_bulk(symbols, "2026-09-01", "2026-09-29")
    assert len(out) == 24, "every healthy symbol should still be fetched"


def test_bulk_respects_its_wall_clock_budget(monkeypatch):
    """The slow pathology: roughly half the requests time out, so the
    consecutive-failure breaker never trips and the run bleeds out anyway."""
    clock = {"t": 0.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])

    def fake_get(url, params=None, timeout=None, **kwargs):
        clock["t"] += 30.0          # every request is slow
        return _Resp(CSV)           # ...but succeeds, so no breaker

    monkeypatch.setattr(mod.requests, "get", fake_get)
    symbols = [f"SYM{i}" for i in range(400)]
    out = USSecondaryProvider().get_ohlcv_bulk(symbols, "2026-09-01", "2026-09-29")

    assert clock["t"] <= mod._BULK_TIME_BUDGET_SECONDS + 30.0
    assert len(out) < len(symbols), "should have stopped well before the end"


def test_giving_up_returns_empty_rather_than_raising(monkeypatch):
    """The caller's contract is unchanged: no secondary data. The quality
    engine already reports that as SKIPPED, not as two sources agreeing --
    an exception here would instead take the market down with it."""
    monkeypatch.setattr(mod.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    out = USSecondaryProvider().get_ohlcv_bulk(["A", "B", "C"], "2026-09-01", "2026-09-29")
    assert out == {}
    assert isinstance(out, dict)


def test_a_single_failed_symbol_returns_an_empty_frame_not_none(monkeypatch):
    monkeypatch.setattr(mod.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("404")))
    df = USSecondaryProvider().get_ohlcv("AAL", "2026-09-01", "2026-09-29")
    assert isinstance(df, pd.DataFrame) and df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]


def test_stooq_contract_error_body_fails_closed(monkeypatch):
    monkeypatch.setattr(
        mod.requests,
        "get",
        lambda *a, **k: _Resp("Get your apikey: https://stooq.com/q/d/?s=aapl.us&get_apikey"),
    )
    df = USSecondaryProvider(api_key="").get_ohlcv(
        "AAPL", "2026-09-01", "2026-09-29"
    )
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "adj_close"]
