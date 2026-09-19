"""
Local graph store backed by the prepared SQLite (investigation.db).

Provides the same query interface as the TigerGraph adapter so the
investigation orchestrator does not need to care which backend is live.

All queries are based on investigation questions from the README and the
official challenge fraud patterns.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.config import settings
from backend.logging import get_logger
from backend.models import (
    TransactionRecord, IdentityRecord, HistoricalCase,
    Channel, DeviceProfileKey,
)

log = get_logger(__name__)

_CONN: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        if not settings.prepared_db.exists():
            raise RuntimeError(
                f"investigation.db not found at {settings.prepared_db}. "
                "Run: python -m backend.scripts.prepare_data"
            )
        _CONN = sqlite3.connect(str(settings.prepared_db), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL")
    return _CONN


def _row_to_txn(r: sqlite3.Row) -> TransactionRecord:
    return TransactionRecord(
        txn_id=str(r["TransactionID"]),
        customer_id=str(r["customer_id"]),
        card_id=str(r["card_id"]),
        ts=datetime.fromisoformat(str(r["ts"])),
        amount=float(r["TransactionAmt"] or 0),
        product_cd=str(r["ProductCD"] or ""),
        channel=Channel(str(r["channel"])) if r["channel"] in ("online", "in_person") else Channel.in_person,
        addr1=str(r["addr1"]) if r["addr1"] else None,
        addr2=str(r["addr2"]) if r["addr2"] else None,
        p_email=str(r["P_emaildomain"]) if r["P_emaildomain"] else None,
        r_email=str(r["R_emaildomain"]) if r["R_emaildomain"] else None,
        risk_score=float(r["risk_score"]) if r["risk_score"] is not None else None,
        c1=float(r["C1"]) if r["C1"] is not None else None,
        d1=float(r["D1"]) if r["D1"] is not None else None,
        m4=str(r["M4"]) if r["M4"] else None,
        has_identity=False,  # set below
    )


def _row_to_identity(r: sqlite3.Row) -> IdentityRecord:
    return IdentityRecord(
        txn_id=str(r["TransactionID"]),
        device_type=str(r["DeviceType"]) if r["DeviceType"] else None,
        device_info=str(r["DeviceInfo"]) if r["DeviceInfo"] else None,
        os=str(r["id_30"]) if r["id_30"] else None,
        browser=str(r["id_31"]) if r["id_31"] else None,
        screen=str(r["id_33"]) if r["id_33"] else None,
        device_status=str(r["id_15"]) if r["id_15"] else None,
        proxy=str(r["id_23"]) if r["id_23"] else None,
        match_status=str(r["id_34"]) if r["id_34"] else None,
    )


def _row_to_closed_case(r: sqlite3.Row) -> HistoricalCase:
    txn_ids = [t.strip() for t in str(r["txn_ids"] or "").split("|") if t.strip()]
    cards = [c.strip() for c in str(r["connected_card_ids"] or "").split("|") if c.strip()]
    actions = [a.strip() for a in str(r["actions_taken"] or "").split("|") if a.strip()]
    return HistoricalCase(
        case_id=str(r["case_id"]),
        customer_id=str(r["customer_id"]),
        card_id=str(r["card_id"]),
        opened_at=datetime.fromisoformat(str(r["opened_at"])),
        closed_at=datetime.fromisoformat(str(r["closed_at"])),
        outcome=str(r["outcome"]),
        pattern=str(r["pattern"]),
        first_fraud_txn_id=str(r["first_fraud_txn_id"]) if r["first_fraud_txn_id"] else None,
        txn_ids=txn_ids,
        n_txns=int(r["n_txns"] or 0),
        exposure_usd=float(r["exposure_usd"] or 0),
        connected_card_ids=cards,
        actions_taken=actions,
        report_filed=str(r["report_filed"]).upper() == "YES",
        analyst_notes=str(r["analyst_notes"] or ""),
    )


# ─── Transaction queries ──────────────────────────────────────────────────────

def get_transaction(txn_id: str) -> TransactionRecord | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT t.*, i.DeviceType FROM transactions t "
        "LEFT JOIN identity i ON i.TransactionID=t.TransactionID "
        "WHERE t.TransactionID=?",
        (txn_id,)
    ).fetchone()
    if row is None:
        return None
    txn = _row_to_txn(row)
    txn.has_identity = row["DeviceType"] is not None
    return txn


def get_card_transaction_history(
    card_id: str, limit: int = 30, before: datetime | None = None
) -> list[TransactionRecord]:
    conn = _get_conn()
    if before:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE card_id=? AND ts <= ? ORDER BY ts DESC LIMIT ?",
            (card_id, before.isoformat(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE card_id=? ORDER BY ts DESC LIMIT ?",
            (card_id, limit),
        ).fetchall()
    return [_row_to_txn(r) for r in rows]


def get_customer_cards(customer_id: str) -> list[str]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT card_id FROM transactions WHERE customer_id=? ORDER BY card_id",
        (customer_id,),
    ).fetchall()
    return [r["card_id"] for r in rows]


def get_card_window(
    card_id: str, center_ts: datetime, hours: int = 48
) -> list[TransactionRecord]:
    """Transactions on a card within ±hours of a timestamp."""
    lo = (center_ts - timedelta(hours=hours)).isoformat()
    hi = (center_ts + timedelta(hours=hours)).isoformat()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE card_id=? AND ts BETWEEN ? AND ? ORDER BY ts",
        (card_id, lo, hi),
    ).fetchall()
    return [_row_to_txn(r) for r in rows]


def get_transaction_identity(txn_id: str) -> IdentityRecord | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM identity WHERE TransactionID=?", (txn_id,)
    ).fetchone()
    return _row_to_identity(row) if row else None


def get_tiny_transaction_sequence(
    card_id: str, center_ts: datetime, window_hours: float = 2.0, amount_threshold: float = 10.0
) -> list[TransactionRecord]:
    """Small-amount online transactions near the center timestamp (card-testing signal)."""
    lo = (center_ts - timedelta(hours=window_hours)).isoformat()
    hi = (center_ts + timedelta(hours=window_hours)).isoformat()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM transactions
           WHERE card_id=? AND ts BETWEEN ? AND ?
             AND channel='online' AND TransactionAmt <= ?
           ORDER BY ts""",
        (card_id, lo, hi, amount_threshold),
    ).fetchall()
    return [_row_to_txn(r) for r in rows]


def get_card_region_history(card_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Addresses and channels used historically on this card."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT addr1, addr2, channel, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
           FROM transactions
           WHERE card_id=? AND addr1 IS NOT NULL
           GROUP BY addr1, addr2, channel
           ORDER BY last_ts DESC
           LIMIT ?""",
        (card_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_card_email_history(card_id: str) -> list[dict[str, Any]]:
    """Purchaser email domains used on this card."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT P_emaildomain, COUNT(*) AS n
           FROM transactions WHERE card_id=? AND P_emaildomain IS NOT NULL
           GROUP BY P_emaildomain ORDER BY n DESC""",
        (card_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_card_product_history(card_id: str) -> list[dict[str, Any]]:
    """Product codes this card typically uses."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ProductCD, COUNT(*) AS n
           FROM transactions WHERE card_id=?
           GROUP BY ProductCD ORDER BY n DESC""",
        (card_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_card_amount_stats(card_id: str) -> dict[str, float]:
    """Min, max, mean, median transaction amounts for this card."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT MIN(TransactionAmt) AS min_amt,
                  MAX(TransactionAmt) AS max_amt,
                  AVG(TransactionAmt) AS avg_amt,
                  COUNT(*) AS n
           FROM transactions WHERE card_id=?""",
        (card_id,),
    ).fetchone()
    return dict(row) if row else {}


# ─── Device and identity queries ──────────────────────────────────────────────

def get_device_profile_label(txn_id: str) -> str | None:
    """Return the canonical '| '-joined device profile label for a transaction."""
    idr = get_transaction_identity(txn_id)
    if not idr:
        return None
    return DeviceProfileKey(
        device_info=idr.device_info or "unknown",
        os=idr.os or "unknown",
        browser=idr.browser or "unknown",
        screen=idr.screen or "unknown",
    ).label()


def get_accounts_sharing_device(device_label: str, limit: int = 20) -> list[dict[str, Any]]:
    """
    Find cards/customers that have used the same device profile (DeviceInfo+OS+browser+screen).
    """
    conn = _get_conn()
    parts = [p.strip() for p in device_label.split("|")]
    if len(parts) < 4:
        return []
    device_info, os_, browser, screen = parts[0], parts[1], parts[2], parts[3]

    rows = conn.execute(
        """
        SELECT DISTINCT t.card_id, t.customer_id
        FROM identity i
        JOIN transactions t ON t.TransactionID = i.TransactionID
        WHERE (COALESCE(i.DeviceInfo, 'unknown') = ?
           OR COALESCE(i.id_30, 'unknown') = ?)
          AND COALESCE(i.id_31, 'unknown') = ?
          AND COALESCE(i.id_33, 'unknown') = ?
        LIMIT ?
        """,
        (device_info, os_, browser, screen, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_card_device_history(card_id: str) -> list[dict[str, Any]]:
    """All distinct device profiles ever used by this card."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT
            COALESCE(i.DeviceInfo, 'unknown') AS device_info,
            COALESCE(i.id_30, 'unknown') AS os,
            COALESCE(i.id_31, 'unknown') AS browser,
            COALESCE(i.id_33, 'unknown') AS screen,
            i.id_15 AS device_status,
            COUNT(*) AS n
        FROM transactions t
        JOIN identity i ON i.TransactionID = t.TransactionID
        WHERE t.card_id=?
        GROUP BY device_info, os, browser, screen
        """,
        (card_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_transaction_velocity(
    card_id: str, center_ts: datetime, hours: float = 24.0
) -> dict[str, Any]:
    """Count and total amount of transactions in a window."""
    lo = (center_ts - timedelta(hours=hours)).isoformat()
    hi = (center_ts + timedelta(hours=hours)).isoformat()
    conn = _get_conn()
    row = conn.execute(
        """SELECT COUNT(*) AS n, SUM(TransactionAmt) AS total_amt
           FROM transactions
           WHERE card_id=? AND ts BETWEEN ? AND ?""",
        (card_id, lo, hi),
    ).fetchone()
    return dict(row) if row else {"n": 0, "total_amt": 0}


# ─── Historical case queries ───────────────────────────────────────────────────

def get_closed_cases_for_customer(customer_id: str) -> list[HistoricalCase]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM closed_cases WHERE customer_id=? ORDER BY opened_at DESC",
        (customer_id,),
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def get_closed_cases_for_card(card_id: str) -> list[HistoricalCase]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM closed_cases WHERE card_id=? ORDER BY opened_at DESC",
        (card_id,),
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def get_closed_cases_involving_txn(txn_id: str) -> list[HistoricalCase]:
    conn = _get_conn()
    # txn_ids column is pipe-separated
    rows = conn.execute(
        """SELECT * FROM closed_cases
           WHERE txn_ids LIKE ? OR txn_ids LIKE ? OR txn_ids LIKE ? OR first_fraud_txn_id=?""",
        (f"{txn_id}|%", f"%|{txn_id}|%", f"%|{txn_id}", txn_id),
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def get_closed_cases_by_device(device_label: str, limit: int = 10) -> list[HistoricalCase]:
    """Cases whose analyst_notes mention this device label string."""
    conn = _get_conn()
    parts = [p.strip() for p in device_label.split("|")]
    device_info = parts[0] if parts else ""
    if not device_info or device_info == "unknown":
        return []
    rows = conn.execute(
        "SELECT * FROM closed_cases WHERE analyst_notes LIKE ? LIMIT ?",
        (f"%{device_info}%", limit),
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def get_closed_cases_by_pattern(pattern: str, limit: int = 15) -> list[HistoricalCase]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM closed_cases WHERE pattern=? ORDER BY closed_at DESC LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def search_closed_cases_text(query: str, limit: int = 5) -> list[HistoricalCase]:
    """Simple keyword search over analyst_notes (BM25 substitute)."""
    conn = _get_conn()
    tokens = [t for t in query.lower().split() if len(t) > 3]
    if not tokens:
        return []
    like_clauses = " OR ".join(["analyst_notes LIKE ?" for _ in tokens])
    params = [f"%{t}%" for t in tokens] + [limit]
    rows = conn.execute(
        f"SELECT * FROM closed_cases WHERE {like_clauses} ORDER BY closed_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_closed_case(r) for r in rows]


def get_connected_card_cases(card_ids: list[str]) -> list[HistoricalCase]:
    """Cases that name any of the given cards in connected_card_ids."""
    if not card_ids:
        return []
    conn = _get_conn()
    results: list[HistoricalCase] = []
    seen = set()
    for cid in card_ids:
        rows = conn.execute(
            "SELECT * FROM closed_cases WHERE connected_card_ids LIKE ? OR card_id=?",
            (f"%{cid}%", cid),
        ).fetchall()
        for r in rows:
            case_id = r["case_id"]
            if case_id not in seen:
                seen.add(case_id)
                results.append(_row_to_closed_case(r))
    return results


# ─── Case pack ────────────────────────────────────────────────────────────────

def get_all_case_triggers() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM case_pack ORDER BY opened_at").fetchall()
    return [dict(r) for r in rows]


def get_case_trigger(case_id: str) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM case_pack WHERE case_id=?", (case_id,)
    ).fetchone()
    return dict(row) if row else None


# ─── Graph neighbor count ─────────────────────────────────────────────────────

def get_cards_in_same_region_window(
    region: str, center_ts: datetime, days: float = 3.0, limit: int = 30
) -> list[dict[str, Any]]:
    """Cards that made in-person transactions in the same region in a time window."""
    lo = (center_ts - timedelta(days=days)).isoformat()
    hi = (center_ts + timedelta(days=days)).isoformat()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT DISTINCT card_id, customer_id
           FROM transactions
           WHERE addr1=? AND channel='in_person' AND ts BETWEEN ? AND ?
           LIMIT ?""",
        (region, lo, hi, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_cards_in_same_email_domain(domain: str) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT card_id, customer_id FROM transactions WHERE P_emaildomain=? LIMIT 50",
        (domain,),
    ).fetchall()
    return [dict(r) for r in rows]


def health_check() -> dict[str, str]:
    try:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM _meta LIMIT 1").fetchone()
        if row:
            return {"status": "healthy", "n_transactions": str(row["n_transactions"]),
                    "prepared_at": str(row["prepared_at"])}
        return {"status": "healthy"}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


# ─── Investigation case persistence (case memory) ──────────────────────────────
#
# The graph store is the case-memory layer: every completed investigation is
# written here so later investigations can retrieve it the same way they
# retrieve closed_cases_history.  This is the local-store implementation of
# what the TigerGraph path does with an InvestigationCase vertex.

_CASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigation_cases (
    case_id            TEXT PRIMARY KEY,
    customer_id        TEXT NOT NULL,
    card_id            TEXT NOT NULL,
    trigger_type       TEXT,
    opened_at          TEXT,
    status             TEXT,
    verdict            TEXT,
    fraud_probability  REAL,
    pattern            TEXT,
    exposure_usd       REAL,
    summary            TEXT,
    written_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ic_cust_idx ON investigation_cases(customer_id);
CREATE INDEX IF NOT EXISTS ic_card_idx ON investigation_cases(card_id);
CREATE INDEX IF NOT EXISTS ic_verdict_idx ON investigation_cases(verdict);

CREATE TABLE IF NOT EXISTS investigation_case_txns (
    case_id  TEXT NOT NULL,
    txn_id   TEXT NOT NULL,
    PRIMARY KEY (case_id, txn_id)
);
CREATE INDEX IF NOT EXISTS ict_txn_idx ON investigation_case_txns(txn_id);

CREATE TABLE IF NOT EXISTS investigation_case_cards (
    case_id  TEXT NOT NULL,
    card_id  TEXT NOT NULL,
    PRIMARY KEY (case_id, card_id)
);

CREATE TABLE IF NOT EXISTS investigation_case_devices (
    case_id       TEXT NOT NULL,
    device_label  TEXT NOT NULL,
    PRIMARY KEY (case_id, device_label)
);
CREATE INDEX IF NOT EXISTS icd_device_idx ON investigation_case_devices(device_label);
"""


def _ensure_case_schema() -> None:
    conn = _get_conn()
    conn.executescript(_CASE_SCHEMA)
    conn.commit()


def write_investigation_case(payload: dict[str, Any]) -> str:
    """
    Upsert a completed investigation case into the graph store.

    `payload` is the InvestigationCase model dumped with mode="json".
    Returns the graph-side case id.
    """
    _ensure_case_schema()
    conn = _get_conn()
    case_id = str(payload["case_id"])
    # Year of the investigation, not the year the binary happens to run in.
    year = (payload.get("trigger", {}).get("opened_at") or payload.get("created_at") or "")[:4]
    graph_case_id = f"CASE-{year}-{case_id}"

    conn.execute(
        """
        INSERT INTO investigation_cases
        (case_id, customer_id, card_id, trigger_type, opened_at, status,
         verdict, fraud_probability, pattern, exposure_usd, summary, written_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(case_id) DO UPDATE SET
            status=excluded.status, verdict=excluded.verdict,
            fraud_probability=excluded.fraud_probability, pattern=excluded.pattern,
            exposure_usd=excluded.exposure_usd, summary=excluded.summary,
            written_at=excluded.written_at
        """,
        (
            case_id,
            str(payload["customer_id"]),
            str(payload["card_id"]),
            payload["trigger"]["trigger_type"],
            payload["trigger"].get("opened_at", ""),
            payload.get("status", ""),
            payload.get("verdict", ""),
            float(payload.get("fraud_probability") or 0.0),
            payload.get("pattern", "none"),
            float(payload.get("exposure_usd") or 0.0),
            (payload.get("summary") or "")[:4000],
            datetime.utcnow().isoformat(),
        ),
    )
    conn.execute("DELETE FROM investigation_case_txns WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM investigation_case_cards WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM investigation_case_devices WHERE case_id=?", (case_id,))

    conn.executemany(
        "INSERT OR IGNORE INTO investigation_case_txns(case_id, txn_id) VALUES (?,?)",
        [(case_id, str(t)) for t in payload.get("affected_txn_ids", [])],
    )
    cards = {payload["card_id"], *payload.get("connected_card_ids", [])}
    conn.executemany(
        "INSERT OR IGNORE INTO investigation_case_cards(case_id, card_id) VALUES (?,?)",
        [(case_id, str(c)) for c in cards if c],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO investigation_case_devices(case_id, device_label) VALUES (?,?)",
        [(case_id, str(d)) for d in payload.get("connected_device_profiles", [])],
    )
    conn.commit()
    return graph_case_id


def get_investigation_cases_for_customer(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Cases previously written to the graph store for this customer."""
    _ensure_case_schema()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM investigation_cases WHERE customer_id=?
           ORDER BY written_at DESC LIMIT ?""",
        (customer_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_investigation_cases_by_device(device_label: str, limit: int = 10) -> list[dict[str, Any]]:
    """Cases sharing a device profile, excluding nothing — used as case memory."""
    _ensure_case_schema()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ic.* FROM investigation_cases ic
           JOIN investigation_case_devices d ON d.case_id = ic.case_id
           WHERE d.device_label=? ORDER BY ic.written_at DESC LIMIT ?""",
        (device_label, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_investigation_cases_involving_txn(txn_id: str, limit: int = 10) -> list[dict[str, Any]]:
    _ensure_case_schema()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ic.* FROM investigation_cases ic
           JOIN investigation_case_txns t ON t.case_id = ic.case_id
           WHERE t.txn_id=? ORDER BY ic.written_at DESC LIMIT ?""",
        (txn_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
