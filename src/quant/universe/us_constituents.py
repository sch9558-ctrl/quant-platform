"""Dynamic US index-constituent discovery (spec section 1: no hardcoded
tickers). Fetches S&P 500 / NASDAQ-100 membership from public reference
tables at run time, with a local JSON cache so repeated runs on the same
day don't re-fetch. A refresh failure may use only a still-fresh cache;
once the cache exceeds CACHE_MAX_AGE_DAYS the universe fails closed rather
than silently screening an obsolete constituent list.

NOTE ON THIS SANDBOX: fetching Wikipedia is not reachable from this
development environment (see README.md). `fetch_sp500_constituents` and
`fetch_nasdaq100_constituents` both accept an injectable `fetch_html_fn` so
they are fully unit-testable offline; the default implementation (used when
`fetch_html_fn=None`) calls `pandas.read_html` against Wikipedia and should
be validated once on a machine with normal internet access.
"""
from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from quant import config
from quant.data.base import MarketDataProvider, SymbolInfo
from quant.utils.logging import get_logger

logger = get_logger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_WIKI_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
SP500_RAW_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NASDAQ100_RAW_URL = "https://raw.githubusercontent.com/Gary-Strauss/nasdaq100-scraper/main/data/nasdaq100_constituents.csv"
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; quant-platform/1.0; +https://github.com/sch9558-ctrl/quant-platform)"}

CACHE_MAX_AGE_DAYS = 1

# a small discovery seed of well-known broad-market ETF tickers. This is NOT
# the final ETF universe (that's determined by the AUM/liquidity rule in
# universe_us.yaml -> major_etf_rule against real AUM/volume data) -- it is
# only a starting point in case NASDAQ Trader's symbol directory is
# unavailable, so the pipeline degrades gracefully rather than shipping zero
# ETFs. Every one of these is still subject to the liquidity/AUM filter.
_ETF_DISCOVERY_SEED = [
    "SPY", "IVV", "VOO", "QQQ", "DIA", "IWM", "VTI", "VEA", "VWO", "AGG",
    "BND", "GLD", "SLV", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP",
]


def _cache_path(name: str) -> Path:
    d = config.resolve_path(config.settings()["paths"]["data_cache"]) / "us_universe"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _load_cache(name: str) -> tuple[list[str], float] | None:
    p = _cache_path(name)
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text())
        return obj["symbols"], obj["fetched_at"]
    except Exception:
        return None


def _save_cache(name: str, symbols: list[str]) -> None:
    _cache_path(name).write_text(json.dumps({"symbols": symbols, "fetched_at": time.time()}))


def _fetch_with_cache(cache_name: str, fetcher: Callable[[], list[str]]) -> list[str]:
    cached = _load_cache(cache_name)
    if cached is not None:
        symbols, fetched_at = cached
        age_days = (time.time() - fetched_at) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            return symbols

    try:
        symbols = fetcher()
        if symbols:
            _save_cache(cache_name, symbols)
            return symbols
    except Exception as e:
        logger.warning("Failed to refresh %s constituents, falling back to cache if any: %s", cache_name, e)

    if cached is not None:
        symbols, fetched_at = cached
        age_days = (time.time() - fetched_at) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            return symbols
        raise RuntimeError(
            f"{cache_name} constituent cache is stale ({age_days:.1f}d >= "
            f"{CACHE_MAX_AGE_DAYS}d) and refresh failed; refusing stale universe"
        )
    raise RuntimeError(
        f"{cache_name} constituent refresh failed and no usable cache exists; "
        "refusing incomplete index universe"
    )


def _read_html_with_headers(url: str) -> list[pd.DataFrame]:
    response = requests.get(url, headers=_HTTP_HEADERS, timeout=20)
    response.raise_for_status()
    return pd.read_html(StringIO(response.text))


def _read_symbol_csv(url: str) -> list[str]:
    response = requests.get(url, headers=_HTTP_HEADERS, timeout=20)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text))
    col = next((x for x in df.columns if str(x).lower() in ("symbol", "ticker")), df.columns[0])
    return [str(s).strip().replace(".", "-") for s in df[col].dropna().tolist()]


def fetch_sp500_constituents(fetch_html_fn: Callable[[str], list[pd.DataFrame]] | None = None) -> list[str]:
    def default_fetcher() -> list[str]:
        try:
            tables = (fetch_html_fn or _read_html_with_headers)(SP500_WIKI_URL)
            df = tables[0]
            col = "Symbol" if "Symbol" in df.columns else df.columns[0]
            symbols = [str(s).strip().replace(".", "-") for s in df[col].tolist()]
            if symbols:
                return symbols
        except Exception as exc:
            logger.warning("Wikipedia S&P 500 fetch failed; trying maintained raw dataset: %s", exc)
        return _read_symbol_csv(SP500_RAW_URL)

    return _fetch_with_cache("sp500.json", default_fetcher)


def fetch_nasdaq100_constituents(fetch_html_fn: Callable[[str], list[pd.DataFrame]] | None = None) -> list[str]:
    def default_fetcher() -> list[str]:
        try:
            tables = (fetch_html_fn or _read_html_with_headers)(NASDAQ100_WIKI_URL)
            for df in tables:
                cols = [c for c in df.columns if str(c).lower() in ("ticker", "symbol")]
                if cols:
                    symbols = [str(s).strip().replace(".", "-") for s in df[cols[0]].tolist()]
                    if symbols:
                        return symbols
        except Exception as exc:
            logger.warning("Wikipedia Nasdaq-100 fetch failed; trying maintained raw dataset: %s", exc)
        return _read_symbol_csv(NASDAQ100_RAW_URL)

    return _fetch_with_cache("nasdaq100.json", default_fetcher)


def discover_major_etfs(provider: MarketDataProvider, as_of: str) -> list[SymbolInfo]:
    """Rule-based major-ETF universe: seed candidates, screened by AUM/volume
    thresholds from config/universe_us.yaml -> major_etf_rule. Approximates
    AUM with market cap when a true AUM figure isn't available from the
    provider.
    """
    cfg = config.universe_config("us")["major_etf_rule"]
    lookback_start = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(30)).strftime("%Y-%m-%d")

    ohlcv_map = provider.get_ohlcv_bulk(_ETF_DISCOVERY_SEED, lookback_start, as_of)
    caps = provider.get_market_cap(_ETF_DISCOVERY_SEED, as_of)

    result: list[SymbolInfo] = []
    for sym in _ETF_DISCOVERY_SEED:
        df = ohlcv_map.get(sym)
        if df is None or df.empty:
            continue
        avg_dollar_vol = float((df["close"] * df["volume"]).mean())
        aum_proxy = caps.get(sym, avg_dollar_vol * 50)  # crude proxy if cap unavailable
        if avg_dollar_vol < cfg["min_avg_dollar_volume_usd"]:
            continue
        if aum_proxy < cfg["min_aum_usd"]:
            continue
        result.append(SymbolInfo(symbol=sym, name=sym, market="us", exchange="NYSE", asset_type="etf"))

    return result


def build_index_based_symbols(provider: MarketDataProvider, as_of: str) -> list[SymbolInfo]:
    """Combine S&P 500 + NASDAQ-100 + rule-discovered major ETFs into a
    SymbolInfo list suitable for UniverseEngine.build(symbols_override=...).
    """
    sp500 = set(fetch_sp500_constituents())
    ndx100 = set(fetch_nasdaq100_constituents())
    equities = sorted(sp500 | ndx100)

    symbols: list[SymbolInfo] = [
        SymbolInfo(symbol=s, name=s, market="us", exchange="NASDAQ", asset_type="equity")
        for s in equities
    ]
    symbols.extend(discover_major_etfs(provider, as_of))
    return symbols
