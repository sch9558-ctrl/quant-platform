"""Research Database (spec section 19): a local SQLite store of every
experiment run, so past results can be found, compared, and reproduced.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from quant import config
from quant.research_db.models import ExperimentRecord

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

    def count(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM experiments")
            return int(cur.fetchone()[0])
