"""Universe Engine (spec section 3).

Turns the raw listed-symbol universe from a MarketDataProvider into a
filtered, config-driven investable universe, and records *why* each symbol
was included or excluded so the decision is auditable.

Point-in-time discipline: `build()` is always called for a specific `as_of`
date and only uses data available up to and including that date. Snapshots
are persisted under `data/processed/universe/<market>/<as_of>.parquet` so a
backtest run on 2019-06-01 reconstructs the universe *as it looked on that
date*, not today's list filtered backwards (which would be survivorship
bias).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant import config
from quant.data.base import MarketDataProvider, SymbolInfo
from quant.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UniverseMember:
    symbol: str
    name: str
    exchange: str
    asset_type: str
    price: float | None
    avg_trading_value: float | None
    market_cap: float | None
    listed_days: int | None
    included: bool
    exclusion_reasons: list[str] = field(default_factory=list)


@dataclass
class UniverseSnapshot:
    market: str
    as_of: pd.Timestamp
    members: list[UniverseMember]

    def included_symbols(self) -> list[str]:
        return [m.symbol for m in self.members if m.included]

    def to_frame(self) -> pd.DataFrame:
        if not self.members:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "symbol": m.symbol, "name": m.name, "exchange": m.exchange,
            "asset_type": m.asset_type, "price": m.price,
            "avg_trading_value": m.avg_trading_value, "market_cap": m.market_cap,
            "listed_days": m.listed_days, "included": m.included,
            "exclusion_reasons": ";".join(m.exclusion_reasons),
        } for m in self.members])
        return df


class UniverseEngine:
    def __init__(self, market: str, provider: MarketDataProvider):
        assert market in ("korea", "us")
        self.market = market
        self.provider = provider
        self.cfg = config.universe_config(market)

    def build(self, as_of: str, symbols_override: list[SymbolInfo] | None = None) -> UniverseSnapshot:
        as_of_ts = pd.Timestamp(as_of)
        symbols_info = symbols_override if symbols_override is not None else self.provider.list_symbols(as_of)

        filt = self.cfg["filters"]
        etf_filt = self.cfg.get("etf_filters", {})
        lookback = filt.get("liquidity_lookback_days", 20)
        lookback_start = (as_of_ts - pd.tseries.offsets.BDay(int(lookback * 1.6))).strftime("%Y-%m-%d")

        equity_symbols = [s.symbol for s in symbols_info if s.asset_type == "equity"]
        etf_symbols = [s.symbol for s in symbols_info if s.asset_type == "etf"] if self.cfg.get("include_etf", True) else []
        relevant_symbols = equity_symbols + etf_symbols

        ohlcv_map = self.provider.get_ohlcv_bulk(relevant_symbols, lookback_start, as_of)
        market_caps = self.provider.get_market_cap(equity_symbols, as_of)

        members: list[UniverseMember] = []
        for info in symbols_info:
            if info.asset_type not in ("equity", "etf"):
                continue
            if info.asset_type == "etf" and not self.cfg.get("include_etf", True):
                continue

            reasons: list[str] = []
            df = ohlcv_map.get(info.symbol)

            price = None
            avg_trading_value = None
            if df is not None and not df.empty:
                tail = df.tail(lookback)
                price = float(tail["close"].iloc[-1])
                avg_trading_value = float((tail["close"] * tail["volume"]).mean())
                last_trade_date = tail.index.max()
                days_since_trade = (as_of_ts - last_trade_date).days
                if days_since_trade > filt.get("max_days_since_last_trade", 5):
                    reasons.append(f"stale_data({days_since_trade}d since last bar)")
            else:
                reasons.append("no_price_data")

            listed_days = None
            if info.listing_date is not None:
                listed_days = (as_of_ts - pd.Timestamp(info.listing_date)).days
                if listed_days < filt.get("min_listed_days", 0):
                    reasons.append(f"too_recently_listed({listed_days}d)")

            market_cap = market_caps.get(info.symbol) if info.asset_type == "equity" else None

            if info.asset_type == "equity":
                if price is not None and price < filt.get("min_price_krw", filt.get("min_price_usd", 0)):
                    reasons.append("price_below_minimum")
                if avg_trading_value is not None and avg_trading_value < filt.get(
                    "min_avg_trading_value_krw", filt.get("min_avg_dollar_volume_usd", 0)
                ):
                    reasons.append("liquidity_below_minimum")
                if market_cap is not None and market_cap < filt.get(
                    "min_market_cap_krw", filt.get("min_market_cap_usd", 0)
                ):
                    reasons.append("market_cap_below_minimum")
                elif market_cap is None:
                    reasons.append("market_cap_unknown")
            else:  # etf
                if avg_trading_value is not None and avg_trading_value < etf_filt.get("min_avg_trading_value_krw", 0):
                    reasons.append("etf_liquidity_below_minimum")

            if filt.get("exclude_administrative_issue", True) and info.is_administrative:
                reasons.append("administrative_issue")
            if filt.get("exclude_trading_halt", True) and info.is_trading_halted:
                reasons.append("trading_halted")
            if not info.is_active:
                reasons.append("inactive_or_delisted")

            members.append(UniverseMember(
                symbol=info.symbol, name=info.name, exchange=info.exchange,
                asset_type=info.asset_type, price=price,
                avg_trading_value=avg_trading_value, market_cap=market_cap,
                listed_days=listed_days, included=(len(reasons) == 0),
                exclusion_reasons=reasons,
            ))

        snapshot = UniverseSnapshot(market=self.market, as_of=as_of_ts, members=members)
        logger.info(
            "Universe[%s] as_of=%s: %d/%d symbols included",
            self.market, as_of, len(snapshot.included_symbols()), len(members),
        )
        return snapshot

    def _snapshot_dir(self, base_dir=None):
        base = base_dir or config.resolve_path(config.settings()["paths"]["data_processed"])
        return base / "universe" / self.market

    def save_snapshot(self, snapshot: UniverseSnapshot, base_dir=None) -> None:
        base = self._snapshot_dir(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{snapshot.as_of.strftime('%Y-%m-%d')}.parquet"
        snapshot.to_frame().to_parquet(path)

    def load_snapshot(self, as_of: str, base_dir=None) -> pd.DataFrame | None:
        base = self._snapshot_dir(base_dir)
        path = base / f"{pd.Timestamp(as_of).strftime('%Y-%m-%d')}.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)
