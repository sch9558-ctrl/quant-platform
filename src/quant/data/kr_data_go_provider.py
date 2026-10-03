"""Primary Korean equity provider using the verified data.go.kr V2 contract.

The Financial Services Commission getStockPriceInfo_V2 endpoint returns a
full KOSPI/KOSDAQ snapshot for one basDt. Daily/short-window research
therefore costs one HTTP request per trading session rather than one request
per listed symbol. The existing KRDataProvider remains the narrow fallback
for long historical windows, benchmark indices and fundamental fields that
the verified snapshot contract does not provide.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

from quant.data.base import SymbolInfo
from quant.data.kr_provider import KRDataProvider
from quant.utils.calendar import default_as_of, trading_days
from quant.utils.logging import get_logger

logger = get_logger(__name__)

DATA_GO_KR_URL = (
    "https://apis.data.go.kr/1160100/service/"
    "GetStockSecuritiesInfoService/getStockPriceInfo_V2"
)
DATA_GO_NUM_ROWS = 3500
MAX_DATA_GO_SNAPSHOT_SESSIONS = 400

COLUMN_MAP = {
    "basDt": "date", "srtnCd": "ticker", "itmsNm": "name", "mrktCtg": "exchange",
    "mkp": "open", "hipr": "high", "lopr": "low", "clpr": "close", "trqu": "volume",
    "trPrc": "turnover", "mrktTotAmt": "market_cap", "fltRt": "change_pct",
}
REQUIRED_FIELDS = set(COLUMN_MAP)
NUMERIC_COLUMNS = ["open","high","low","close","volume","turnover","market_cap","change_pct"]
PRICE_COLUMNS = ["open","high","low","close","volume"]


class DataGoKrProvider(KRDataProvider):
    """KOSPI/KOSDAQ provider backed primarily by data.go.kr daily snapshots."""

    def __init__(self, request_sleep_sec: float = 0.05, service_key: str | None = None,
                 cache_dir: str | Path = "data/cache/kr", timeout: int = 25):
        super().__init__(request_sleep_sec=request_sleep_sec)
        raw_key = service_key if service_key is not None else os.getenv("DATA_GO_KR_SERVICE_KEY", "")
        self.service_key = unquote(raw_key).strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = int(timeout)

    def _cache_path(self, date_str: str | pd.Timestamp) -> Path:
        return self.cache_dir / f"kr_market_{self._fmt(date_str)}.csv"

    def _load_cached_snapshot(self, date_str: str | pd.Timestamp) -> pd.DataFrame | None:
        path = self._cache_path(date_str)
        if not path.is_file():
            return None
        try:
            df = pd.read_csv(path, dtype={"ticker": str}, parse_dates=["date"])
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
            return df
        except Exception as exc:
            logger.warning("KR data.go.kr cache unreadable (%s): %s", path, exc)
            return None

    def _write_snapshot_cache(self, date_str: str | pd.Timestamp, df: pd.DataFrame) -> None:
        path = self._cache_path(date_str)
        tmp = path.with_suffix(path.suffix + ".tmp")
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        out.to_csv(tmp, index=False)
        tmp.replace(path)

    def fetch_daily_snapshot(self, date_str: str | pd.Timestamp) -> pd.DataFrame:
        clean_date = self._fmt(date_str)
        cached = self._load_cached_snapshot(clean_date)
        if cached is not None:
            return cached
        if not self.service_key:
            raise RuntimeError("DATA_GO_KR_SERVICE_KEY is not set; refusing to fabricate or silently substitute the primary Korean daily snapshot.")
        params = {"serviceKey": self.service_key, "resultType": "json",
                  "numOfRows": str(DATA_GO_NUM_ROWS), "pageNo": "1", "basDt": clean_date}
        response = requests.get(DATA_GO_KR_URL, params=params, timeout=self.timeout)
        try:
            response.raise_for_status()
            if response.text.lstrip().startswith("<"):
                raise RuntimeError(f"data.go.kr returned XML/error content: {response.text[:300]}")
            payload = response.json()
        finally:
            self._sleep()

        envelope = payload.get("response", {}) if isinstance(payload, dict) else {}
        header = envelope.get("header") or {}
        code = str(header.get("resultCode", "00"))
        if code not in {"0","00","0000"}:
            raise RuntimeError(f"data.go.kr error {code}: {header.get('resultMsg') or header}")
        body = envelope.get("body") or {}
        try:
            total_count = int(body.get("totalCount") or 0)
        except (TypeError, ValueError):
            total_count = 0
        if total_count > DATA_GO_NUM_ROWS:
            raise RuntimeError(f"data.go.kr totalCount={total_count} exceeds numOfRows={DATA_GO_NUM_ROWS}; refusing a silently truncated market snapshot.")
        items = body.get("items") or {}
        raw_items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not raw_items:
            return pd.DataFrame(columns=list(COLUMN_MAP.values()))
        raw = pd.DataFrame(raw_items)
        missing = sorted(REQUIRED_FIELDS - set(raw.columns))
        if missing:
            raise RuntimeError(f"data.go.kr response contract changed; missing fields: {missing}")

        df = raw.rename(columns=COLUMN_MAP)[list(COLUMN_MAP.values())].copy()
        df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="raise")
        df["exchange"] = df["exchange"].astype(str).str.upper()
        df = df[df["exchange"].isin(["KOSPI","KOSDAQ"])].copy()
        for col in NUMERIC_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.drop_duplicates(subset=["date","ticker"], keep="last").sort_values("ticker").reset_index(drop=True)
        self._write_snapshot_cache(clean_date, df)
        return df

    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        as_of = as_of or default_as_of("korea")
        snapshot = self.fetch_daily_snapshot(as_of)
        if snapshot.empty:
            return []
        return [SymbolInfo(symbol=str(r.ticker), name=str(r.name), market="korea",
                           exchange=str(r.exchange), asset_type="equity")
                for r in snapshot[["ticker","name","exchange"]].drop_duplicates("ticker").itertuples(index=False)]

    def _all_cached(self, sessions: pd.DatetimeIndex) -> bool:
        return all(self._cache_path(ts).is_file() for ts in sessions)

    def _snapshot_bulk(self, symbols: list[str], sessions: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
        wanted = set(symbols)
        collected = []
        for ts in sessions:
            daily = self.fetch_daily_snapshot(ts)
            if daily.empty:
                continue
            sub = daily[daily["ticker"].isin(wanted)][["date","ticker",*PRICE_COLUMNS]].copy()
            if not sub.empty:
                collected.append(sub)
        if not collected:
            return {}
        rows = pd.concat(collected, ignore_index=True)
        out = {}
        for ticker, group in rows.groupby("ticker", sort=False):
            frame = group.set_index("date")[PRICE_COLUMNS].astype(float).sort_index()
            frame = frame[~frame.index.duplicated(keep="last")]
            frame["adj_close"] = frame["close"]
            frame.index.name = "date"
            out[str(ticker)] = frame
        return out

    def get_ohlcv(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        symbol = str(symbol).zfill(6)
        try:
            sessions = trading_days(start, end, "korea")
        except Exception as exc:
            logger.warning("KR trading-calendar lookup failed (%s); using business days", exc)
            sessions = pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end))
        if len(sessions) == 0:
            return pd.DataFrame(columns=[*PRICE_COLUMNS,"adj_close"])
        if len(sessions) <= MAX_DATA_GO_SNAPSHOT_SESSIONS or self._all_cached(sessions):
            return self._snapshot_bulk([symbol], sessions).get(symbol, pd.DataFrame(columns=[*PRICE_COLUMNS,"adj_close"]))
        return KRDataProvider.get_ohlcv(self, symbol, start, end)

    def get_ohlcv_bulk(self, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
        symbols = list(dict.fromkeys(str(s).zfill(6) for s in symbols))
        if not symbols:
            return {}
        try:
            sessions = trading_days(start, end, "korea")
        except Exception as exc:
            logger.warning("KR trading-calendar lookup failed (%s); using business days", exc)
            sessions = pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end))
        if len(sessions) == 0:
            return {}
        if len(sessions) <= MAX_DATA_GO_SNAPSHOT_SESSIONS or self._all_cached(sessions):
            return self._snapshot_bulk(symbols, sessions)
        out = {}
        for symbol in symbols:
            frame = KRDataProvider.get_ohlcv(self, symbol, start, end)
            if frame is not None and not frame.empty:
                out[symbol] = frame
        return out

    def get_market_cap(self, symbols: list[str], as_of: str) -> pd.Series:
        snapshot = self.fetch_daily_snapshot(as_of)
        if snapshot.empty:
            return pd.Series(dtype=float, name="market_cap")
        wanted = set(str(s).zfill(6) for s in symbols)
        sub = snapshot[snapshot["ticker"].isin(wanted)].drop_duplicates("ticker")
        return pd.Series(sub["market_cap"].values, index=sub["ticker"].astype(str), name="market_cap", dtype=float)
