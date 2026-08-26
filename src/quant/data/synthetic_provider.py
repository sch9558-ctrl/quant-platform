"""Synthetic (fully offline, deterministic) market data provider.

Two uses:
  1. Unit/integration tests for everything downstream of the data layer
     (universe, features, scanner, strategies, backtester, ranking, ...)
     run against this instead of the network, so they are fast, free, and
     reproducible in any environment -- including this development sandbox,
     which has no route to KRX/Yahoo (see README.md).
  2. `--demo` mode on the CLI scripts, so a user can see the entire
     `python run_research.py` pipeline work end-to-end on day one, before
     confirming their own machine's network access to pykrx/yfinance.

Prices follow a per-symbol geometric random walk with mildly mean-reverting
volatility regimes so that trend/momentum/mean-reversion/volatility
strategies all have *something* real to find -- this is not meant to be a
realistic market simulator, just a stable, non-degenerate fixture.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.data.base import MarketDataProvider, SymbolInfo

_SECTORS = [
    "Technology", "Financials", "Industrials", "Healthcare", "Consumer",
    "Energy", "Materials", "Utilities", "RealEstate", "Communication",
]


class SyntheticDataProvider(MarketDataProvider):
    def __init__(
        self,
        market: str,
        n_symbols: int = 60,
        n_etfs: int = 8,
        start: str = "2012-01-01",
        end: str | None = None,
        seed: int = 42,
    ):
        assert market in ("korea", "us")
        self.market = market
        self._rng = np.random.default_rng(seed)
        self._start = pd.Timestamp(start)
        self._end = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
        self._dates = pd.bdate_range(self._start, self._end)
        self._n_symbols = n_symbols
        self._n_etfs = n_etfs
        self._prefix = "K" if market == "korea" else "US"
        self._symbols_info: dict[str, SymbolInfo] = {}
        self._panels: dict[str, pd.DataFrame] = {}
        self._shares_out: dict[str, float] = {}
        self._fundamentals: dict[str, dict] = {}
        self._build()

    # -- construction -----------------------------------------------------
    def _build(self) -> None:
        n_total = self._n_symbols + self._n_etfs
        exchanges = (["KOSPI", "KOSDAQ"] if self.market == "korea" else ["NYSE", "NASDAQ", "AMEX"])

        for i in range(n_total):
            is_etf = i >= self._n_symbols
            sym = f"{self._prefix}{'ETF' if is_etf else 'EQ'}{i:04d}"
            exchange = self._rng.choice(exchanges)
            sector = None if is_etf else self._rng.choice(_SECTORS)
            listing_offset_days = int(self._rng.integers(0, int(len(self._dates) * 0.3)))
            listing_date = self._dates[min(listing_offset_days, len(self._dates) - 1)]

            self._symbols_info[sym] = SymbolInfo(
                symbol=sym, name=f"{sym} Corp" if not is_etf else f"{sym} Fund",
                market=self.market, exchange=exchange,
                asset_type="etf" if is_etf else "equity",
                sector=sector, listing_date=listing_date, is_active=True,
            )

            self._panels[sym] = self._simulate_path(sym, listing_date)
            base_price = float(self._panels[sym]["close"].iloc[-1])
            self._shares_out[sym] = float(self._rng.uniform(5e6, 5e8))

            if not is_etf:
                self._fundamentals[sym] = {
                    "per": float(self._rng.uniform(5, 40)),
                    "pbr": float(self._rng.uniform(0.5, 6)),
                    "roe": float(self._rng.uniform(-0.05, 0.30)),
                    "eps": float(self._rng.uniform(-5, 50)),
                    "eps_growth": float(self._rng.normal(0.05, 0.20)),
                    "revenue_growth": float(self._rng.normal(0.05, 0.15)),
                    "operating_margin": float(self._rng.uniform(-0.05, 0.35)),
                    "debt_ratio": float(self._rng.uniform(0.0, 1.5)),
                    "dividend_yield": float(max(0.0, self._rng.normal(0.02, 0.02))),
                }

    def _simulate_path(self, symbol: str, listing_date: pd.Timestamp) -> pd.DataFrame:
        dates = self._dates[self._dates >= listing_date]
        n = len(dates)
        if n == 0:
            dates = self._dates[-2:]
            n = len(dates)

        rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
        annual_drift = rng.normal(0.06, 0.10)
        base_vol = rng.uniform(0.15, 0.45)

        # regime-switching volatility multiplier (mean-reverting AR(1) in log-vol)
        vol_mult = np.ones(n)
        for t in range(1, n):
            shock = rng.normal(0, 0.15)
            vol_mult[t] = np.clip(vol_mult[t - 1] * np.exp(shock - 0.02 * (vol_mult[t - 1] - 1)), 0.4, 3.0)

        daily_vol = base_vol / np.sqrt(252) * vol_mult
        daily_drift = annual_drift / 252
        # small autocorrelated momentum term so trend/momentum strategies have signal
        momentum_state = 0.0
        rets = np.empty(n)
        for t in range(n):
            momentum_state = 0.9 * momentum_state + rng.normal(0, 0.01)
            rets[t] = daily_drift + momentum_state + rng.normal(0, daily_vol[t])

        start_price = rng.uniform(10, 200)
        close = start_price * np.exp(np.cumsum(rets))
        open_ = close * (1 + rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
        base_volume = rng.uniform(5e4, 5e6)
        volume = np.abs(rng.normal(base_volume, base_volume * 0.4, n)) * (1 + 2 * (vol_mult - 1).clip(min=0))

        df = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume.round().astype(np.int64),
        }, index=dates)
        df["adj_close"] = df["close"]
        df.index.name = "date"
        return df

    # -- MarketDataProvider interface -------------------------------------
    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        return list(self._symbols_info.values())

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        panel = self._panels.get(symbol)
        if panel is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])
        return panel.loc[pd.Timestamp(start):pd.Timestamp(end)].copy()

    def get_market_cap(self, symbols: list[str], as_of: str) -> pd.Series:
        out = {}
        as_of_ts = pd.Timestamp(as_of)
        for sym in symbols:
            panel = self._panels.get(sym)
            if panel is None or panel.empty:
                continue
            sub = panel.loc[:as_of_ts]
            if sub.empty:
                continue
            price = sub["close"].iloc[-1]
            out[sym] = float(price * self._shares_out.get(sym, 0))
        return pd.Series(out, name="market_cap")

    def get_fundamentals(self, symbols: list[str], as_of: str) -> pd.DataFrame:
        rows = []
        for sym in symbols:
            f = self._fundamentals.get(sym)
            if f is None:
                continue
            rows.append({"symbol": sym, "market_cap": self.get_market_cap([sym], as_of).get(sym), **f})
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("symbol")

    def get_index_ohlcv(self, index_symbol: str, start: str, end: str) -> pd.DataFrame:
        equities = [s for s, info in self._symbols_info.items() if info.asset_type == "equity"]
        frames = []
        for sym in equities:
            df = self.get_ohlcv(sym, start, end)
            if not df.empty:
                frames.append(df["close"].rename(sym))
        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])
        panel = pd.concat(frames, axis=1).sort_index()
        # normalize each series to 100 at first available value, then average -> synthetic index level
        normed = panel.apply(lambda s: 100 * s / s.dropna().iloc[0] if s.dropna().size else s)
        level = normed.mean(axis=1, skipna=True)
        idx_df = pd.DataFrame({
            "open": level, "high": level, "low": level, "close": level, "adj_close": level,
            "volume": panel.count(axis=1) * 1_000_000,
        })
        idx_df.index.name = "date"
        return idx_df
