"""
SQLite-based durable store for investigation state, audit events, approvals.
Completely separate from the prepared graph/investigation DB.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.logging import get_logger

log = get_logger(__name__)

_DB: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        _DB = _open()
    return _DB


def _open() -> sqlite3.Connection:
    path = settings.app_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    log.info("app_db.opened", path=str(path))
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS investigations (
        case_id     TEXT PRIMARY KEY,
        state       TEXT NOT NULL,
        payload     TEXT NOT NULL,   -- JSON of InvestigationCase
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_events (
        event_id    TEXT PRIMARY KEY,
        case_id     TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        state_from  TEXT,
        state_to    TEXT,
        actor       TEXT,
        metadata    TEXT,            -- JSON
        timestamp   TEXT NOT NULL,
        FOREIGN KEY (case_id) REFERENCES investigations(case_id)
    );

    CREATE INDEX IF NOT EXISTS audit_events_case ON audit_events(case_id);

    CREATE TABLE IF NOT EXISTS approvals (
        approval_id  TEXT PRIMARY KEY,
        case_id      TEXT NOT NULL,
        payload      TEXT NOT NULL,  -- JSON of ApprovalRequest
        created_at   TEXT NOT NULL,
        FOREIGN KEY (case_id) REFERENCES investigations(case_id)
    );

    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key         TEXT PRIMARY KEY,
        case_id     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    """)
    conn.commit()


# ─── investigation CRUD ───────────────────────────────────────────────────────

def save_investigation(case_id: str, state: str, payload: dict[str, Any]) -> None:
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO investigations(case_id, state, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            state=excluded.state,
            payload=excluded.payload,
            updated_at=excluded.updated_at
        """,
        (case_id, state, json.dumps(payload), now, now),
    )
    conn.commit()


def load_investigation(case_id: str) -> dict[str, Any] | None:
    conn = get_db()
    row = conn.execute(
        "SELECT payload FROM investigations WHERE case_id=?", (case_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload"])


def list_investigations(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT case_id, state, updated_at FROM investigations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── audit events ─────────────────────────────────────────────────────────────

def append_audit_event(evt: dict[str, Any]) -> None:
    conn = get_db()
    conn.execute(
        """
        INSERT OR IGNORE INTO audit_events
        (event_id, case_id, event_type, state_from, state_to, actor, metadata, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evt["event_id"],
            evt["case_id"],
            evt["event_type"],
            evt.get("state_from"),
            evt.get("state_to"),
            evt.get("actor", "agent"),
            json.dumps(evt.get("metadata", {})),
            evt.get("timestamp", datetime.utcnow().isoformat()),
        ),
    )
    conn.commit()


def get_audit_trail(case_id: str) -> list[dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE case_id=? ORDER BY timestamp",
        (case_id,),
    ).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                pass
        events.append(d)
    return events


# ─── approvals ────────────────────────────────────────────────────────────────

def save_approval(approval_id: str, case_id: str, payload: dict[str, Any]) -> None:
    conn = get_db()
    conn.execute(
        """
        INSERT INTO approvals(approval_id, case_id, payload, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(approval_id) DO UPDATE SET payload=excluded.payload
        """,
        (approval_id, case_id, json.dumps(payload), datetime.utcnow().isoformat()),
    )
    conn.commit()


def load_approval(approval_id: str) -> dict[str, Any] | None:
    conn = get_db()
    row = conn.execute(
        "SELECT payload FROM approvals WHERE approval_id=?", (approval_id,)
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def list_pending_approvals(case_id: str) -> list[dict[str, Any]]:
    conn = get_db()
    rows = conn.execute(
        "SELECT payload FROM approvals WHERE case_id=?", (case_id,)
    ).fetchall()
    results = []
    for r in rows:
        p = json.loads(r["payload"])
        if p.get("status") == "pending":
            results.append(p)
    return results


# ─── idempotency ──────────────────────────────────────────────────────────────

def check_idempotency(key: str) -> str | None:
    """Return existing case_id if this key was already used, else None."""
    conn = get_db()
    row = conn.execute(
        "SELECT case_id FROM idempotency_keys WHERE key=?", (key,)
    ).fetchone()
    return row["case_id"] if row else None


def register_idempotency(key: str, case_id: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO idempotency_keys(key, case_id, created_at) VALUES (?,?,?)",
        (key, case_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
