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

DATA_GO_KR_URLS = (
    "https://apis.data.go.kr/1160100/GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2",
    "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo_V2",
)
# Backwards-compatible alias used by tests/integrations that import the old name.
DATA_GO_KR_URL = DATA_GO_KR_URLS[0]
DATA_GO_NUM_ROWS = 3500
MAX_DATA_GO_SNAPSHOT_SESSIONS = 450
MAX_METADATA_BACKTRACK_SESSIONS = 5

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

    def _request_daily_snapshot(self, clean_date: str) -> pd.DataFrame:
        params = {
            "serviceKey": self.service_key,
            "resultType": "json",
            "numOfRows": str(DATA_GO_NUM_ROWS),
            "pageNo": "1",
            "basDt": clean_date,
        }
        failures: list[str] = []
        for url in DATA_GO_KR_URLS:
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                if response.text.lstrip().startswith("<"):
                    raise RuntimeError(
                        f"data.go.kr returned XML/error content: {response.text[:300]}"
                    )
                payload = response.json()
                envelope = payload.get("response", {}) if isinstance(payload, dict) else {}
                header = envelope.get("header") or {}
                code = str(header.get("resultCode", "00"))
                if code not in {"0", "00", "0000"}:
                    raise RuntimeError(
                        f"data.go.kr error {code}: {header.get('resultMsg') or header}"
                    )
                body = envelope.get("body") or {}
                try:
                    total_count = int(body.get("totalCount") or 0)
                except (TypeError, ValueError):
                    total_count = 0
                if total_count > DATA_GO_NUM_ROWS:
                    raise RuntimeError(
                        f"data.go.kr totalCount={total_count} exceeds "
                        f"numOfRows={DATA_GO_NUM_ROWS}; refusing a silently "
                        "truncated market snapshot."
                    )
                items = body.get("items") or {}
                raw_items = items.get("item", []) if isinstance(items, dict) else items
                if isinstance(raw_items, dict):
                    raw_items = [raw_items]
                if not raw_items:
                    raise RuntimeError(
                        f"data.go.kr returned no rows for basDt={clean_date}"
                    )
                raw = pd.DataFrame(raw_items)
                missing = sorted(REQUIRED_FIELDS - set(raw.columns))
                if missing:
                    raise RuntimeError(
                        f"data.go.kr response contract changed; missing fields: {missing}"
                    )
                df = raw.rename(columns=COLUMN_MAP)[list(COLUMN_MAP.values())].copy()
                df["ticker"] = df["ticker"].astype(str).str.zfill(6)
                df["date"] = pd.to_datetime(
                    df["date"], format="%Y%m%d", errors="raise"
                )
                df["exchange"] = df["exchange"].astype(str).str.upper()
                df = df[df["exchange"].isin(["KOSPI", "KOSDAQ"])].copy()
                for col in NUMERIC_COLUMNS:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                if df.empty:
                    raise RuntimeError(
                        f"data.go.kr returned no KOSPI/KOSDAQ rows for {clean_date}"
                    )
                return (
                    df.drop_duplicates(subset=["date", "ticker"], keep="last")
                    .sort_values("ticker")
                    .reset_index(drop=True)
                )
            except Exception as exc:
                failures.append(f"{url}: {type(exc).__name__}: {exc}")
            finally:
                self._sleep()
        raise RuntimeError(
            f"data.go.kr snapshot unavailable for basDt={clean_date}; "
            + " | ".join(failures)
        )


    def _pykrx_exact_snapshot(self, clean_date: str) -> pd.DataFrame:
        """Fallback exact-session snapshot from KRX via pykrx.

        This fallback is used only when data.go.kr explicitly has *no rows*
        for an otherwise valid trading date. It never changes the requested
        date and therefore cannot disguise a stale bar as current.
        """
        from pykrx import stock

        frames = []
        for market_name in ("KOSPI", "KOSDAQ"):
            try:
                raw = stock.get_market_ohlcv_by_ticker(clean_date, market=market_name)
            except Exception as exc:
                logger.warning(
                    "pykrx exact %s snapshot failed for %s: %s",
                    market_name, clean_date, exc,
                )
                continue
            finally:
                self._sleep()
            if raw is None or raw.empty:
                continue

            renamed = raw.rename(columns={
                "시가": "open", "고가": "high", "저가": "low", "종가": "close",
                "거래량": "volume", "거래대금": "turnover", "등락률": "change_pct",
            }).copy()
            required = {"open", "high", "low", "close", "volume"}
            if not required.issubset(renamed.columns):
                continue

            market_cap = None
            try:
                caps = stock.get_market_cap_by_ticker(clean_date, market=market_name)
                if caps is not None and not caps.empty and "시가총액" in caps.columns:
                    market_cap = pd.to_numeric(caps["시가총액"], errors="coerce")
            except Exception as exc:
                logger.warning(
                    "pykrx exact %s market-cap fetch failed for %s: %s",
                    market_name, clean_date, exc,
                )
            finally:
                self._sleep()

            frame = pd.DataFrame({
                "date": pd.Timestamp(clean_date),
                "ticker": renamed.index.astype(str).str.zfill(6),
                # Metadata names are deliberately not invented here.
                # list_symbols() uses the separately backfilled data.go snapshot.
                "name": renamed.index.astype(str).str.zfill(6),
                "exchange": market_name,
                "open": pd.to_numeric(renamed["open"], errors="coerce").values,
                "high": pd.to_numeric(renamed["high"], errors="coerce").values,
                "low": pd.to_numeric(renamed["low"], errors="coerce").values,
                "close": pd.to_numeric(renamed["close"], errors="coerce").values,
                "volume": pd.to_numeric(renamed["volume"], errors="coerce").values,
                "turnover": pd.to_numeric(
                    renamed.get("turnover", pd.Series(index=renamed.index, dtype=float)),
                    errors="coerce",
                ).values,
                "market_cap": (
                    market_cap.reindex(renamed.index).values
                    if market_cap is not None
                    else float("nan")
                ),
                "change_pct": pd.to_numeric(
                    renamed.get("change_pct", pd.Series(index=renamed.index, dtype=float)),
                    errors="coerce",
                ).values,
            })
            frames.append(frame)

        if not frames:
            return pd.DataFrame(columns=list(COLUMN_MAP.values()))
        out = pd.concat(frames, ignore_index=True)
        return (
            out.drop_duplicates(subset=["date", "ticker"], keep="last")
            .sort_values("ticker")
            .reset_index(drop=True)
        )

    def fetch_daily_snapshot(self, date_str: str | pd.Timestamp) -> pd.DataFrame:
        """Fetch the exact requested trading date; never relabel stale data."""
        clean_date = self._fmt(date_str)
        cached = self._load_cached_snapshot(clean_date)
        if cached is not None:
            return cached
        if not self.service_key:
            raise RuntimeError(
                "DATA_GO_KR_SERVICE_KEY is not set; refusing to fabricate or "
                "silently substitute the primary Korean daily snapshot."
            )
        try:
            df = self._request_daily_snapshot(clean_date)
        except RuntimeError as exc:
            message = str(exc)
            publication_lag = (
                "returned no rows for basDt=" in message
                or "returned no KOSPI/KOSDAQ rows" in message
            )
            if not publication_lag:
                raise
            logger.warning(
                "data.go.kr has not published %s yet; trying exact-session pykrx fallback",
                clean_date,
            )
            df = self._pykrx_exact_snapshot(clean_date)
            if df.empty:
                raise
            actual = pd.Timestamp(df["date"].max()).strftime("%Y%m%d")
            if actual != clean_date:
                raise RuntimeError(
                    f"pykrx fallback returned {actual}, expected exact session {clean_date}"
                ) from exc
        self._write_snapshot_cache(clean_date, df)
        return df

    def fetch_latest_available_snapshot(
        self,
        as_of: str | pd.Timestamp,
        max_backtrack_sessions: int = MAX_METADATA_BACKTRACK_SESSIONS,
    ) -> tuple[str, pd.DataFrame]:
        """Metadata helper only: find the newest actually published snapshot.

        This is safe for symbol-directory/market-cap discovery. Price-quality
        validation still requests every exact session and will mark a missing
        latest bar stale instead of pretending this fallback is current.
        """
        end = pd.Timestamp(as_of).normalize()
        start = end - pd.Timedelta(days=max(14, max_backtrack_sessions * 3))
        try:
            sessions = list(trading_days(start, end, "korea"))
        except Exception:
            sessions = list(pd.bdate_range(start, end))
        failures: list[str] = []
        for ts in reversed(sessions[-(max_backtrack_sessions + 1):]):
            try:
                # Metadata availability follows data.go publication, not the
                # pykrx price fallback. This preserves the true metadata date.
                df = self._request_daily_snapshot(self._fmt(ts))
                actual = pd.Timestamp(df["date"].max()).strftime("%Y-%m-%d")
                if actual != end.strftime("%Y-%m-%d"):
                    logger.warning(
                        "KR metadata snapshot lag: requested=%s available=%s",
                        end.strftime("%Y-%m-%d"),
                        actual,
                    )
                return actual, df
            except Exception as exc:
                failures.append(f"{pd.Timestamp(ts).date()}: {exc}")
        raise RuntimeError(
            f"No data.go.kr market snapshot available through {end.date()}; "
            + " | ".join(failures)
        )

    def resolve_as_of(
        self,
        requested_as_of: str | pd.Timestamp,
        max_lag_sessions: int = 1,
    ) -> str:
        """Return the newest data.go session within an explicit lag budget.

        The returned date is the date actually analysed. An older bar is
        never relabelled as the requested session.
        """
        expected = pd.Timestamp(requested_as_of).normalize()
        try:
            df = self._request_daily_snapshot(self._fmt(expected))
            self._write_snapshot_cache(expected, df)
            return expected.strftime("%Y-%m-%d")
        except Exception as exact_exc:
            actual_str, df = self.fetch_latest_available_snapshot(expected)
            actual = pd.Timestamp(actual_str).normalize()
            if actual > expected:
                raise RuntimeError(
                    f"KR provider returned future session {actual.date()} for {expected.date()}"
                ) from exact_exc
            try:
                sessions = trading_days(actual, expected, "korea")
                lag = max(len(sessions) - 1, 0)
            except Exception:
                lag = max(len(pd.bdate_range(actual, expected)) - 1, 0)
            if lag > int(max_lag_sessions):
                raise RuntimeError(
                    f"KR provider data is {lag} session(s) behind requested "
                    f"{expected.date()} (latest published {actual.date()}, "
                    f"max allowed {max_lag_sessions})."
                ) from exact_exc
            self._write_snapshot_cache(actual, df)
            logger.warning(
                "KR provider publication lag: requested=%s actual=%s lag=%d session(s)",
                expected.date(), actual.date(), lag,
            )
            return actual.strftime("%Y-%m-%d")

    def _metadata_snapshot(
        self, as_of: str | pd.Timestamp,
    ) -> tuple[str, pd.DataFrame]:
        """Prefer the exact/cached session and only then backtrack metadata."""
        clean = pd.Timestamp(as_of).strftime("%Y-%m-%d")
        cached = self._load_cached_snapshot(clean)
        if cached is not None and not cached.empty:
            return clean, cached
        try:
            df = self._request_daily_snapshot(self._fmt(as_of))
            self._write_snapshot_cache(as_of, df)
            return clean, df
        except Exception:
            return self.fetch_latest_available_snapshot(as_of)

    def list_symbols(self, as_of: str | None = None) -> list[SymbolInfo]:
        as_of = as_of or default_as_of("korea")
        _, snapshot = self._metadata_snapshot(as_of)
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
        consecutive_failures = 0
        for ts in sessions:
            try:
                daily = self.fetch_daily_snapshot(ts)
                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                logger.warning("KR exact-session snapshot unavailable for %s: %s", ts, exc)
                # If credentials/the service are wholly unavailable, avoid
                # hundreds of identical calls. A missing latest one or two
                # sessions is still preserved as an honest quality failure.
                if consecutive_failures >= 3:
                    logger.error("Stopping KR snapshot range after 3 consecutive failures.")
                    break
                continue
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
        _, snapshot = self._metadata_snapshot(as_of)
        if snapshot.empty:
            return pd.Series(dtype=float, name="market_cap")
        wanted = set(str(s).zfill(6) for s in symbols)
        sub = snapshot[snapshot["ticker"].isin(wanted)].drop_duplicates("ticker")
        return pd.Series(sub["market_cap"].values, index=sub["ticker"].astype(str), name="market_cap", dtype=float)
