"""Cross-asset market snapshot and institutional risk gates."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class MacroGate:
    macro_risk_elevated: bool
    position_scale: float
    block_high_beta_growth: bool
    reasons: tuple[str, ...]
    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CrossAssetSnapshot:
    as_of: str
    usdkrw_1d_pct: float | None
    sox_1d_pct: float | None
    vix: float | None
    us10y_change_bp: float | None
    korea_complete: bool
    us_complete: bool
    source: str
    error: str | None = None

    def complete_for(self, market: str) -> bool:
        if market == "korea":
            return self.korea_complete
        if market == "us":
            return self.us_complete
        return False

    def to_dict(self):
        return asdict(self)


def evaluate_macro_gate(*, market, usdkrw_1d_pct=None, sox_1d_pct=None, vix=None, us10y_change_bp=None):
    reasons = []
    scale = 1.0
    block = False
    if market == "korea":
        if usdkrw_1d_pct is not None and float(usdkrw_1d_pct) >= 0.8:
            reasons.append("USDKRW_SPIKE")
        if sox_1d_pct is not None and float(sox_1d_pct) <= -2.5:
            reasons.append("SOX_CRASH")
        if reasons:
            scale = 0.5
    elif market == "us":
        if vix is not None and float(vix) > 25:
            reasons.append("VIX_ABOVE_25")
            block = True
        if us10y_change_bp is not None and float(us10y_change_bp) >= 15:
            reasons.append("US10Y_RATE_SHOCK")
            scale = min(scale, 0.75)
    else:
        raise ValueError("market must be korea or us")
    return MacroGate(bool(reasons), scale, block, tuple(reasons))


def _close_series(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker in raw.columns.get_level_values(0):
                close = raw[ticker]["Close"]
            elif ticker in raw.columns.get_level_values(-1):
                close = raw["Close"][ticker]
            else:
                return pd.Series(dtype=float)
        else:
            close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce").dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.sort_index()
    except Exception:
        return pd.Series(dtype=float)


def _pct_change_1d(series: pd.Series) -> float | None:
    if len(series) < 2:
        return None
    prev, last = float(series.iloc[-2]), float(series.iloc[-1])
    if prev == 0:
        return None
    return (last / prev - 1.0) * 100.0


def fetch_cross_asset_snapshot(as_of: str, *, downloader: Callable | None = None) -> CrossAssetSnapshot:
    """Fetch one timestamp-consistent macro snapshot through Yahoo Finance.

    KRW=X is USD/KRW, ^SOX is the Philadelphia Semiconductor Index,
    ^VIX is CBOE VIX, and ^TNX is the CBOE 10-year Treasury yield index.
    A partial response stays visible but is not considered complete.
    """
    end = pd.Timestamp(as_of).normalize()
    start = end - pd.Timedelta(days=12)
    tickers = ["KRW=X", "^SOX", "^VIX", "^TNX"]
    try:
        if downloader is None:
            import yfinance as yf
            downloader = yf.download
        raw = downloader(
            tickers,
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
        series = {ticker: _close_series(raw, ticker).loc[:end] for ticker in tickers}
        usdkrw = _pct_change_1d(series["KRW=X"])
        sox = _pct_change_1d(series["^SOX"])
        vix = float(series["^VIX"].iloc[-1]) if len(series["^VIX"]) else None
        tnx = series["^TNX"]
        us10y_bp = (
            (float(tnx.iloc[-1]) - float(tnx.iloc[-2])) * 10.0
            if len(tnx) >= 2 else None
        )
        korea_complete = usdkrw is not None and sox is not None
        us_complete = vix is not None and us10y_bp is not None
        return CrossAssetSnapshot(
            as_of=str(end.date()),
            usdkrw_1d_pct=usdkrw,
            sox_1d_pct=sox,
            vix=vix,
            us10y_change_bp=us10y_bp,
            korea_complete=korea_complete,
            us_complete=us_complete,
            source="Yahoo Finance KRW=X,^SOX,^VIX,^TNX",
            error=None if (korea_complete and us_complete) else "partial macro snapshot",
        )
    except Exception as exc:
        return CrossAssetSnapshot(
            as_of=str(end.date()),
            usdkrw_1d_pct=None,
            sox_1d_pct=None,
            vix=None,
            us10y_change_bp=None,
            korea_complete=False,
            us_complete=False,
            source="Yahoo Finance KRW=X,^SOX,^VIX,^TNX",
            error=type(exc).__name__,
        )
