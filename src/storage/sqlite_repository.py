"""
src/storage/sqlite_repository.py
==================================
SQLite implementation of SignalWatchRepository.

All tables are created with CREATE TABLE IF NOT EXISTS, so initialising
twice is safe.  Re-ingesting the same observation is idempotent via
INSERT OR IGNORE.

Schema summary
--------------
watchlist        (product_id PK, product_name, active, added_at)
observations     (product_id, merchant, observed_at  UNIQUE triplet, price, ...)
bocpd_state      (product_id, merchant  PK pair, state_json, last_price, ...)
change_events    (event_id PK, product_id, merchant, event_json, status, ...)
assessments      (event_id PK, assessment_json, created_at)
pipeline_runs    (run_id PK, started_at, finished_at, ...)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.adapters.price_observation import PriceObservation
from src.storage.repository import SignalWatchRepository

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"NEW", "INVESTIGATING", "INVESTIGATED", "FAILED"}

_DDL = """
CREATE TABLE IF NOT EXISTS watchlist (
    product_id   TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    added_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   TEXT NOT NULL,
    merchant     TEXT NOT NULL,
    observed_at  TEXT NOT NULL,
    price        REAL NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'USD',
    availability TEXT,
    condition    TEXT,
    is_sale      INTEGER,
    shipping     TEXT,
    product_url  TEXT,
    brand        TEXT,
    category     TEXT,
    manufacturer TEXT,
    asin         TEXT,
    ean          TEXT,
    upc          TEXT,
    manufacturer_number TEXT,
    source       TEXT,
    UNIQUE (product_id, merchant, observed_at)
);

CREATE TABLE IF NOT EXISTS bocpd_state (
    product_id         TEXT NOT NULL,
    merchant           TEXT NOT NULL,
    state_json         TEXT NOT NULL,
    last_price         REAL NOT NULL,
    last_observed_at   TEXT NOT NULL,
    observation_count  INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (product_id, merchant)
);

CREATE TABLE IF NOT EXISTS change_events (
    event_id    TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL,
    merchant    TEXT NOT NULL,
    event_json  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'NEW',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    event_id        TEXT PRIMARY KEY,
    assessment_json TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id                 TEXT PRIMARY KEY,
    started_at             TEXT NOT NULL,
    finished_at            TEXT,
    observations_ingested  INTEGER DEFAULT 0,
    events_created         INTEGER DEFAULT 0,
    events_investigated    INTEGER DEFAULT 0,
    search_queries_used    INTEGER DEFAULT 0,
    channel3_calls_used    INTEGER DEFAULT 0,
    errors_json            TEXT DEFAULT '[]'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_to_int(val: Optional[bool]) -> Optional[int]:
    """Convert True/False/None -> 1/0/None for SQLite INTEGER."""
    if val is None:
        return None
    return 1 if val else 0


def _int_to_bool(val: Optional[int]) -> Optional[bool]:
    if val is None:
        return None
    return bool(val)


class SqliteRepository(SignalWatchRepository):
    """
    SQLite-backed repository.

    Parameters
    ----------
    db_path : str or Path
        Path to the SQLite database file.
        Use ":memory:" for an in-memory database (testing).
    """

    def __init__(self, db_path: str = "data/signalwatch.db") -> None:
        self._db_path = str(db_path)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,   # autocommit; we manage transactions explicitly
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript(_DDL)
        logger.debug("SqliteRepository: schema initialised at %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    def add_to_watchlist(self, product_id: str, product_name: str) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT INTO watchlist (product_id, product_name, active, added_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(product_id) DO UPDATE SET
                   product_name = excluded.product_name,
                   active = 1""",
            (product_id, product_name, _now()),
        )
        logger.debug("Watchlist: added %s", product_id)

    def remove_from_watchlist(self, product_id: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE watchlist SET active = 0 WHERE product_id = ?",
            (product_id,),
        )

    def get_watchlist(self, active_only: bool = True) -> List[Dict[str, Any]]:
        conn = self._connect()
        if active_only:
            rows = conn.execute(
                "SELECT * FROM watchlist WHERE active = 1 ORDER BY added_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM watchlist ORDER BY added_at"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def upsert_observation(self, obs: PriceObservation) -> bool:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO observations
                   (product_id, merchant, observed_at, price, currency,
                    availability, condition, is_sale, shipping, product_url,
                    brand, category, manufacturer, asin, ean, upc,
                    manufacturer_number, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obs.product_id, obs.merchant, obs.observed_at,
                    obs.price, obs.currency or "USD",
                    obs.availability, obs.condition,
                    _bool_to_int(obs.is_sale),
                    obs.shipping, obs.product_url,
                    obs.brand, obs.category, obs.manufacturer,
                    obs.asin, obs.ean, obs.upc, obs.manufacturer_number,
                    obs.source,
                ),
            )
            inserted = conn.execute("SELECT changes()").fetchone()[0]
            return inserted > 0
        except sqlite3.IntegrityError:
            return False

    def get_observations(
        self,
        product_id: str,
        merchant: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        sql = "SELECT * FROM observations WHERE product_id = ? AND merchant = ?"
        params: list = [product_id, merchant]
        if since:
            sql += " AND observed_at > ?"
            params.append(since)
        if until:
            sql += " AND observed_at <= ?"
            params.append(until)
        sql += " ORDER BY observed_at"
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["is_sale"] = _int_to_bool(d.get("is_sale"))
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # BOCPD state
    # ------------------------------------------------------------------

    def save_bocpd_state(
        self,
        product_id: str,
        merchant: str,
        state: Dict[str, Any],
        last_price: float,
        last_observed_at: str,
        observation_count: int,
    ) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT INTO bocpd_state
               (product_id, merchant, state_json, last_price, last_observed_at,
                observation_count, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(product_id, merchant) DO UPDATE SET
                   state_json = excluded.state_json,
                   last_price = excluded.last_price,
                   last_observed_at = excluded.last_observed_at,
                   observation_count = excluded.observation_count,
                   updated_at = excluded.updated_at""",
            (product_id, merchant, json.dumps(state), last_price,
             last_observed_at, observation_count, _now()),
        )

    def load_bocpd_state(
        self, product_id: str, merchant: str
    ) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM bocpd_state WHERE product_id = ? AND merchant = ?",
            (product_id, merchant),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json"))
        return d

    # ------------------------------------------------------------------
    # Change events
    # ------------------------------------------------------------------

    def save_change_event(self, event_dict: Dict[str, Any]) -> None:
        conn = self._connect()
        now = _now()
        conn.execute(
            """INSERT OR IGNORE INTO change_events
               (event_id, product_id, merchant, event_json, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                event_dict["event_id"],
                event_dict.get("product_id", ""),
                event_dict.get("merchant", ""),
                json.dumps(event_dict),
                "NEW",
                now, now,
            ),
        )

    def get_events_by_status(self, status: str) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM change_events WHERE status = ? ORDER BY created_at",
            (status,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["event"] = json.loads(d.pop("event_json"))
            result.append(d)
        return result

    def update_event_status(
        self, event_id: str, status: str, error: Optional[str] = None
    ) -> None:
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Must be one of {_VALID_STATUSES}"
            )
        conn = self._connect()
        conn.execute(
            "UPDATE change_events SET status = ?, error = ?, updated_at = ? WHERE event_id = ?",
            (status, error, _now(), event_id),
        )

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------

    def save_assessment(self, event_id: str, assessment_dict: Dict[str, Any]) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO assessments (event_id, assessment_json, created_at)
               VALUES (?,?,?)""",
            (event_id, json.dumps(assessment_dict, default=str), _now()),
        )

    def get_assessment(self, event_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM assessments WHERE event_id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["assessment"] = json.loads(d.pop("assessment_json"))
        return d

    # ------------------------------------------------------------------
    # Pipeline runs
    # ------------------------------------------------------------------

    def start_pipeline_run(self) -> str:
        run_id = "run_" + uuid.uuid4().hex[:12]
        conn = self._connect()
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, started_at) VALUES (?,?)",
            (run_id, _now()),
        )
        return run_id

    def finish_pipeline_run(
        self,
        run_id: str,
        observations_ingested: int,
        events_created: int,
        events_investigated: int,
        search_queries_used: int,
        channel3_calls_used: int,
        errors: List[str],
    ) -> None:
        conn = self._connect()
        conn.execute(
            """UPDATE pipeline_runs SET
               finished_at = ?,
               observations_ingested = ?,
               events_created = ?,
               events_investigated = ?,
               search_queries_used = ?,
               channel3_calls_used = ?,
               errors_json = ?
               WHERE run_id = ?""",
            (
                _now(), observations_ingested, events_created,
                events_investigated, search_queries_used,
                channel3_calls_used, json.dumps(errors), run_id,
            ),
        )
