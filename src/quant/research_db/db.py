"""Research Database (spec section 19): a local SQLite store of every
experiment run, so past results can be found, compared, and reproduced.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from quant import config
from quant.research_db.models import ExperimentRecord, PointInTimeObservation


class DuplicateObservationError(ValueError):
    """The same logical observation at the same publication instant already exists."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    market TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    params_json TEXT NOT NULL,
    universe_description TEXT,
    backtest_start TEXT,
    backtest_end TEXT,
    is_metrics_json TEXT,
    oos_metrics_json TEXT,
    aggregate_oos_metrics_json TEXT,
    cost_config_json TEXT,
    code_version TEXT,
    dataset_version TEXT,
    composite_score REAL,
    overfitting_risk TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_experiments_market ON experiments(market);
CREATE INDEX IF NOT EXISTS idx_experiments_strategy ON experiments(strategy_id);
CREATE INDEX IF NOT EXISTS idx_experiments_created_at ON experiments(created_at);

CREATE TABLE IF NOT EXISTS point_in_time_observations (
    observation_id TEXT PRIMARY KEY,
    observation_type TEXT NOT NULL,
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT,
    published_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    effective_at TEXT,
    payload_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pit_type ON point_in_time_observations(observation_type);
CREATE INDEX IF NOT EXISTS idx_pit_source ON point_in_time_observations(source);
CREATE INDEX IF NOT EXISTS idx_pit_market_symbol ON point_in_time_observations(market, symbol);
CREATE INDEX IF NOT EXISTS idx_pit_published ON point_in_time_observations(published_at);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    commission REAL NOT NULL,
    tax_or_fee REAL NOT NULL,
    filled_at TEXT NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_paper_fills_market_session
ON paper_fills(market, session_date);

CREATE TABLE IF NOT EXISTS paper_account_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    session_date TEXT NOT NULL,
    event_seq INTEGER NOT NULL,
    cash REAL NOT NULL,
    nav REAL NOT NULL,
    peak_nav REAL NOT NULL,
    consecutive_losses INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_snapshots_market_session
ON paper_account_snapshots(market, session_date, event_seq);

CREATE TABLE IF NOT EXISTS paper_position_snapshots (
    snapshot_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    entry_session TEXT,
    PRIMARY KEY(snapshot_id, symbol),
    FOREIGN KEY(snapshot_id) REFERENCES paper_account_snapshots(snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol
ON paper_position_snapshots(symbol);
"""


class ResearchDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else config.resolve_path(config.settings()["research_db"]["path"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def save_experiment(self, record: ExperimentRecord) -> str:
        row = record.to_row()
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO experiments ({', '.join(cols)}) VALUES ({placeholders})"
        with self._connect() as conn:
            conn.execute(sql, [row[c] for c in cols])
        return record.experiment_id

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,))
            row = cur.fetchone()
        return ExperimentRecord.from_row(dict(row)) if row else None

    def query_experiments(
        self,
        market: str | None = None,
        strategy_id: str | None = None,
        since: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses, params = [], []
        if market:
            clauses.append("market = ?")
            params.append(market)
        if strategy_id:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(pd.Timestamp(since).isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT experiment_id, created_at, market, strategy_id, params_json,
                   backtest_start, backtest_end, composite_score, overfitting_risk
            FROM experiments {where}
            ORDER BY created_at DESC LIMIT ?
        """
        params.append(limit)
        with self._connect() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    def latest_experiment(self, market: str, strategy_id: str) -> ExperimentRecord | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM experiments WHERE market = ? AND strategy_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (market, strategy_id),
            )
            row = cur.fetchone()
        return ExperimentRecord.from_row(dict(row)) if row else None

    def delete_experiment(self, experiment_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM experiments WHERE experiment_id = ?", (experiment_id,))

    def save_observation(self, record: PointInTimeObservation) -> str:
        """Append one public release without overwriting earlier revisions.

        Identity is derived from (type, source, market, symbol, published_at),
        so callers do not invent ids. A later published_at is a normal
        revision and inserts another row. Re-inserting the exact same public
        release raises a domain error rather than leaking sqlite details.
        """
        row = record.to_row()
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        sql = (
            f"INSERT INTO point_in_time_observations ({', '.join(cols)}) "
            f"VALUES ({placeholders})"
        )
        try:
            with self._connect() as conn:
                conn.execute(sql, [row[c] for c in cols])
        except sqlite3.IntegrityError as exc:
            raise DuplicateObservationError(
                "same logical observation at the same published_at already exists: "
                f"type={record.observation_type!r}, source={record.source!r}, "
                f"market={record.market!r}, symbol={record.symbol!r}, "
                f"published_at={pd.Timestamp(record.published_at).isoformat()}"
            ) from exc
        return str(row["observation_id"])

    def latest_observation_as_of(
        self,
        *,
        observation_type: str,
        market: str,
        as_of: str | pd.Timestamp,
        source: str | None = None,
        symbol: str | None = None,
    ) -> PointInTimeObservation | None:
        """Return only information published no later than the requested as-of."""
        clauses = [
            "observation_type = ?",
            "market = ?",
            "published_at <= ?",
        ]
        params: list[object] = [
            observation_type,
            market,
            pd.Timestamp(as_of).isoformat(),
        ]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if symbol is None:
            clauses.append("symbol IS NULL")
        else:
            clauses.append("symbol = ?")
            params.append(symbol)
        sql = (
            "SELECT * FROM point_in_time_observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY published_at DESC, collected_at DESC LIMIT 1"
        )
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return PointInTimeObservation.from_row(dict(row)) if row else None

    def query_observations_as_of(
        self,
        *,
        observation_type: str,
        market: str,
        as_of: str | pd.Timestamp,
        source: str | None = None,
        symbol: str | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Historical-safe query: future publication timestamps are excluded."""
        clauses = [
            "observation_type = ?",
            "market = ?",
            "published_at <= ?",
        ]
        params: list[object] = [
            observation_type,
            market,
            pd.Timestamp(as_of).isoformat(),
        ]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        sql = (
            "SELECT observation_id, observation_type, source, market, symbol, "
            "published_at, collected_at, effective_at, payload_json, provenance_json "
            "FROM point_in_time_observations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY published_at DESC, collected_at DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)


    @staticmethod
    def _paper_snapshot_id(
        *,
        market: str,
        session: str | pd.Timestamp,
        event_seq: int,
        cash: float,
        nav: float,
        peak_nav: float,
        consecutive_losses: int,
        positions: dict[str, dict],
    ) -> str:
        normalized = {
            "market": str(market),
            "session": pd.Timestamp(session).normalize().date().isoformat(),
            "event_seq": int(event_seq),
            "cash": round(float(cash), 10),
            "nav": round(float(nav), 10),
            "peak_nav": round(float(peak_nav), 10),
            "consecutive_losses": int(consecutive_losses),
            "positions": {
                str(symbol): {
                    "quantity": round(float(row["quantity"]), 10),
                    "avg_cost": round(float(row["avg_cost"]), 10),
                    "entry_session": row.get("entry_session"),
                }
                for symbol, row in sorted(positions.items())
            },
        }
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def save_paper_state(
        self,
        *,
        market: str,
        session: str | pd.Timestamp,
        event_seq: int,
        cash: float,
        nav: float,
        peak_nav: float,
        consecutive_losses: int,
        positions: dict[str, dict],
        fills: list[dict],
    ) -> str:
        """Persist an immutable audit projection of the authoritative paper broker.

        The broker remains the operational ledger. ResearchDB keeps reproducible
        session/fill history for long-horizon validation and historical queries.
        """
        session_date = pd.Timestamp(session).normalize().date().isoformat()
        snapshot_id = self._paper_snapshot_id(
            market=market,
            session=session_date,
            event_seq=event_seq,
            cash=cash,
            nav=nav,
            peak_nav=peak_nav,
            consecutive_losses=consecutive_losses,
            positions=positions,
        )
        with self._connect() as conn:
            for fill in fills:
                fill_session = pd.Timestamp(fill["session"]).normalize().date().isoformat()
                row = (
                    str(fill["fill_id"]), str(market), fill_session, str(fill["symbol"]),
                    str(fill["side"]), float(fill["quantity"]), float(fill["price"]),
                    float(fill["commission"]), float(fill["tax_or_fee"]),
                    pd.Timestamp(fill["filled_at"]).isoformat(), str(fill.get("reason") or ""),
                )
                existing = conn.execute(
                    "SELECT market, session_date, symbol, side, quantity, price, commission, "
                    "tax_or_fee, filled_at, reason FROM paper_fills WHERE fill_id = ?",
                    (row[0],),
                ).fetchone()
                if existing is not None:
                    existing_tuple = tuple(existing)
                    if existing_tuple != row[1:]:
                        raise ValueError(
                            f"paper fill_id {row[0]!r} already exists with different contents"
                        )
                    continue
                conn.execute(
                    "INSERT INTO paper_fills "
                    "(fill_id, market, session_date, symbol, side, quantity, price, "
                    "commission, tax_or_fee, filled_at, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )

            existing_snapshot = conn.execute(
                "SELECT 1 FROM paper_account_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing_snapshot is None:
                conn.execute(
                    "INSERT INTO paper_account_snapshots "
                    "(snapshot_id, market, session_date, event_seq, cash, nav, peak_nav, consecutive_losses) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_id, str(market), session_date, int(event_seq),
                        float(cash), float(nav), float(peak_nav), int(consecutive_losses),
                    ),
                )
                for symbol, position in sorted(positions.items()):
                    conn.execute(
                        "INSERT INTO paper_position_snapshots "
                        "(snapshot_id, symbol, quantity, avg_cost, entry_session) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            snapshot_id, str(symbol), float(position["quantity"]),
                            float(position["avg_cost"]), position.get("entry_session"),
                        ),
                    )
        return snapshot_id

    def latest_paper_state_as_of(
        self,
        *,
        market: str,
        as_of: str | pd.Timestamp,
    ) -> dict | None:
        """Return the latest persisted broker projection visible by as_of session."""
        cutoff = pd.Timestamp(as_of).normalize().date().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_account_snapshots "
                "WHERE market = ? AND session_date <= ? "
                "ORDER BY session_date DESC, event_seq DESC, rowid DESC LIMIT 1",
                (market, cutoff),
            ).fetchone()
            if row is None:
                return None
            positions = conn.execute(
                "SELECT symbol, quantity, avg_cost, entry_session "
                "FROM paper_position_snapshots WHERE snapshot_id = ? ORDER BY symbol",
                (row["snapshot_id"],),
            ).fetchall()
        return {
            "snapshot_id": row["snapshot_id"],
            "market": row["market"],
            "session": row["session_date"],
            "event_seq": int(row["event_seq"]),
            "cash": float(row["cash"]),
            "nav": float(row["nav"]),
            "peak_nav": float(row["peak_nav"]),
            "consecutive_losses": int(row["consecutive_losses"]),
            "positions": {
                p["symbol"]: {
                    "quantity": float(p["quantity"]),
                    "avg_cost": float(p["avg_cost"]),
                    "entry_session": p["entry_session"],
                }
                for p in positions
            },
        }

    def paper_nav_history(
        self,
        *,
        market: str,
        as_of: str | pd.Timestamp | None = None,
        since: str | pd.Timestamp | None = None,
    ) -> pd.Series:
        """Latest marked NAV per session, suitable for multi-month validation."""
        clauses = ["market = ?"]
        params: list[object] = [market]
        if as_of is not None:
            clauses.append("session_date <= ?")
            params.append(pd.Timestamp(as_of).normalize().date().isoformat())
        if since is not None:
            clauses.append("session_date >= ?")
            params.append(pd.Timestamp(since).normalize().date().isoformat())
        sql = (
            "SELECT session_date, event_seq, nav FROM paper_account_snapshots WHERE "
            + " AND ".join(clauses)
            + " ORDER BY session_date ASC, event_seq ASC, rowid ASC"
        )
        with self._connect() as conn:
            frame = pd.read_sql_query(sql, conn, params=params)
        if frame.empty:
            return pd.Series(dtype=float, name="nav")
        latest = frame.drop_duplicates(subset=["session_date"], keep="last")
        return pd.Series(
            latest["nav"].astype(float).to_numpy(),
            index=pd.to_datetime(latest["session_date"]),
            name="nav",
        )

    def paper_fills_as_of(
        self,
        *,
        market: str,
        as_of: str | pd.Timestamp,
    ) -> pd.DataFrame:
        cutoff = pd.Timestamp(as_of).normalize().date().isoformat()
        with self._connect() as conn:
            return pd.read_sql_query(
                "SELECT * FROM paper_fills WHERE market = ? AND session_date <= ? "
                "ORDER BY session_date, filled_at, fill_id",
                conn,
                params=[market, cutoff],
            )


    def save_quality_quarantine_snapshot(
        self,
        *,
        market: str,
        session: str | pd.Timestamp,
        quarantined_symbols: list[str],
        resolution: str | None,
        raw_passed: bool | None,
        validation_pass: bool,
        quarantine_fraction: float | None = None,
    ) -> str:
        """Persist one market-session quarantine verdict in the existing PIT store.

        This is an audit observation, not a second quality ledger. Re-running
        the same market/session with the same verdict is idempotent; a changed
        verdict for an already-recorded session is rejected rather than
        rewriting history.
        """
        published_at = pd.Timestamp(session).normalize()
        payload = {
            "quarantined_symbols": sorted({str(s) for s in quarantined_symbols}),
            "resolution": resolution,
            "raw_passed": raw_passed,
            "validation_pass": bool(validation_pass),
            "quarantine_fraction": (
                None if quarantine_fraction is None else float(quarantine_fraction)
            ),
        }
        record = PointInTimeObservation(
            observation_type="quality_quarantine_snapshot",
            source="data_quality_engine",
            market=str(market),
            symbol=None,
            published_at=published_at,
            collected_at=pd.Timestamp.now(tz="UTC"),
            effective_at=published_at,
            payload=payload,
            provenance={"session": published_at.date().isoformat()},
        )
        try:
            return self.save_observation(record)
        except DuplicateObservationError:
            existing = self.latest_observation_as_of(
                observation_type="quality_quarantine_snapshot",
                source="data_quality_engine",
                market=str(market),
                symbol=None,
                as_of=published_at,
            )
            if (
                existing is not None
                and pd.Timestamp(existing.published_at).normalize() == published_at
                and existing.payload == payload
            ):
                return str(existing.observation_id)
            raise

    def quality_quarantine_streaks(
        self,
        *,
        market: str,
        as_of: str | pd.Timestamp,
        alert_sessions: int,
        limit: int = 1000,
    ) -> dict:
        """Return consecutive validated-session quarantine streaks as of a session.

        A market validation failure breaks every streak. Missing calendar days
        do not matter: consecutiveness is defined over recorded market
        validation sessions, not wall-clock days.
        """
        frame = self.query_observations_as_of(
            observation_type="quality_quarantine_snapshot",
            source="data_quality_engine",
            market=str(market),
            symbol=None,
            as_of=pd.Timestamp(as_of).normalize(),
            limit=limit,
        )
        if frame.empty:
            return {
                "latest_session": None,
                "streaks": {},
                "alert_sessions": int(alert_sessions),
                "alert_symbols": [],
            }

        rows = []
        for _, row in frame.iterrows():
            rows.append({
                "session": pd.Timestamp(row["published_at"]).normalize(),
                "payload": json.loads(row["payload_json"]),
            })
        # Defensive de-duplication; deterministic observation identity should
        # already ensure one row per market/session.
        by_session = {}
        for row in rows:
            by_session.setdefault(row["session"], row["payload"])
        ordered = sorted(by_session.items(), key=lambda x: x[0], reverse=True)
        latest_session = ordered[0][0]

        latest_payload = ordered[0][1]
        if not bool(latest_payload.get("validation_pass")):
            return {
                "latest_session": latest_session.date().isoformat(),
                "streaks": {},
                "alert_sessions": int(alert_sessions),
                "alert_symbols": [],
            }

        current = set(latest_payload.get("quarantined_symbols") or [])
        streaks = {symbol: 1 for symbol in current}
        for _, payload in ordered[1:]:
            if not bool(payload.get("validation_pass")):
                break
            symbols = set(payload.get("quarantined_symbols") or [])
            continuing = [symbol for symbol in streaks if streaks[symbol] > 0]
            if not continuing:
                break
            for symbol in continuing:
                if symbol in symbols:
                    streaks[symbol] += 1
                else:
                    streaks[symbol] = -streaks[symbol]
        streaks = {symbol: count for symbol, count in streaks.items() if count > 0}
        threshold = int(alert_sessions)
        return {
            "latest_session": latest_session.date().isoformat(),
            "streaks": dict(sorted(streaks.items())),
            "alert_sessions": threshold,
            "alert_symbols": sorted(
                symbol for symbol, count in streaks.items() if count >= threshold
            ),
        }


    def count(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM experiments")
            return int(cur.fetchone()[0])
