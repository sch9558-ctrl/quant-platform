"""Best-effort FX reference snapshots for dashboard display.

FX is informational only and never gates candidate generation. The value is
collected server-side with the research snapshot so the browser does not
contact a third-party FX endpoint or silently mix timestamps.
"""
from __future__ import annotations

import pandas as pd


def _last_close(frame) -> float | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        close = frame["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce").dropna()
        if close.empty:
            return None
        value = float(close.iloc[-1])
        return value if value > 0 else None
    except Exception:
        return None


def fetch_usdkrw_reference() -> dict:
    """Latest available USD/KRW quote from Yahoo Finance (ticker KRW=X).

    Failure is represented explicitly rather than substituted with a stale
    hard-coded rate.
    """
    generated_at = pd.Timestamp.now(tz="UTC").isoformat()
    try:
        import yfinance as yf

        frame = yf.download(
            "KRW=X",
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        rate = _last_close(frame)
        if rate is None:
            raise RuntimeError("USD/KRW quote had no usable close")
        quote_date = (
            str(pd.Timestamp(frame.index[-1]).date())
            if len(frame.index)
            else None
        )
        return {
            "available": True,
            "pair": "USD/KRW",
            "rate": round(rate, 4),
            "quote_date": quote_date,
            "retrieved_at": generated_at,
            "source": "Yahoo Finance KRW=X",
            "note_ko": "대시보드 생성 시 수집한 최근 이용 가능 환율입니다. 실시간 체결환율이 아닙니다.",
        }
    except Exception as exc:
        return {
            "available": False,
            "pair": "USD/KRW",
            "rate": None,
            "quote_date": None,
            "retrieved_at": generated_at,
            "source": "Yahoo Finance KRW=X",
            "error": str(exc),
            "note_ko": "환율 수집에 실패해 미국 종목은 USD 원화면 그대로 표시합니다.",
        }
