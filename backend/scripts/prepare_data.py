"""
Data preparation script.

Reads the four CSVs and writes a slim SQLite database (investigation.db) with:

  - transactions (investigation columns only, not V1-V339)
  - identity
  - closed_cases
  - case_pack (the 20 exam cases)
  - card_id_map   (derived C00123-K1/K2 → fingerprint)

Run:
    python -m backend.scripts.prepare_data
"""
from __future__ import annotations

import hashlib
import itertools
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

# Allow running as a top-level script
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.config import settings
from backend.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

# ─── Column selection ─────────────────────────────────────────────────────────

# Investigation-relevant transaction columns only (skip V1-V339 bulk)
TXN_KEEP = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "dist1", "dist2",
    "P_emaildomain", "R_emaildomain",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14",
    "D1", "D2", "D3", "D4", "D5",
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9",
    # A few Vesta features known to be useful signals
    "V20", "V45", "V127", "V130", "V131", "V307", "V308", "V309", "V310",
    # Added columns
    "customer_id", "ts", "channel", "risk_score",
]

IDENTITY_KEEP = [
    "TransactionID",
    "id_01", "id_02", "id_05", "id_06", "id_11",
    "id_12", "id_13", "id_14", "id_15", "id_16",
    "id_23", "id_30", "id_31", "id_33", "id_34", "id_35", "id_36", "id_37", "id_38",
    "DeviceType", "DeviceInfo",
]


def _fingerprint(row: pd.Series) -> str:
    """Stable card fingerprint from card1-card6 and customer_id."""
    key = "|".join(str(row.get(c, "")) for c in ["customer_id", "card1", "card2", "card3", "card4", "card5", "card6"])
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _derive_card_ids(txn: pd.DataFrame, case_pack: pd.DataFrame, closed_cases: pd.DataFrame) -> pd.DataFrame:
    """
    Derive card_id (e.g., C12345-K1) for each transaction.

    Strategy:
    1. Start with known card_ids from case_pack + closed_cases linked via flagged_txn_id/txn_ids.
    2. Any other fingerprint for a customer: assign next K index.
    """
    log.info("deriving card_ids")

    # Build fingerprints
    txn = txn.copy()
    txn["_fp"] = txn.apply(_fingerprint, axis=1)

    # Collect known txn_id → card_id mappings
    known: dict[str, str] = {}

    # From case_pack
    for _, r in case_pack.iterrows():
        tid = str(r["flagged_txn_id"])
        cid = str(r["card_id"])
        if tid and cid:
            known[tid] = cid

    # From closed_cases – txn_ids is pipe-separated list
    for _, r in closed_cases.iterrows():
        cid = str(r.get("card_id", ""))
        txn_ids_raw = str(r.get("txn_ids", ""))
        for tid in txn_ids_raw.split("|"):
            tid = tid.strip()
            if tid and cid:
                known[tid] = cid

    # Map fingerprint → card_id from known txns
    fp_to_cardid: dict[str, str] = {}
    txn_id_str = txn["TransactionID"].astype(str)
    for i, row in txn.iterrows():
        tid = str(row["TransactionID"])
        if tid in known:
            fp = row["_fp"]
            fp_to_cardid[fp] = known[tid]

    # For remaining fingerprints: assign K-index
    # Group by customer_id, enumerate unique fingerprints in first-seen order
    customer_fp_idx: dict[str, dict[str, str]] = {}
    result_card_ids: list[str] = []

    for _, row in txn.iterrows():
        cust = str(row["customer_id"])
        fp = row["_fp"]
        if fp in fp_to_cardid:
            result_card_ids.append(fp_to_cardid[fp])
        else:
            if cust not in customer_fp_idx:
                customer_fp_idx[cust] = {}
            if fp not in customer_fp_idx[cust]:
                # Find next unused K index
                existing = set(fp_to_cardid.get(f, "") for f in customer_fp_idx.get(cust, {}).values())
                existing.update(fp_to_cardid.values())
                assigned = set(
                    v for k, v in fp_to_cardid.items() if v.startswith(cust + "-K")
                )
                assigned.update(
                    v for _, mapping in customer_fp_idx.items() for v in mapping.values()
                    if v.startswith(cust + "-K")
                )
                k = 1
                while f"{cust}-K{k}" in assigned:
                    k += 1
                card_id = f"{cust}-K{k}"
                customer_fp_idx[cust][fp] = card_id
                fp_to_cardid[fp] = card_id
            result_card_ids.append(customer_fp_idx[cust][fp])

    txn["card_id"] = result_card_ids
    txn = txn.drop(columns=["_fp"])
    return txn


def prepare() -> None:
    t0 = time.time()
    db_path = settings.prepared_db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("prepare_data.start",
             transactions=str(settings.transactions_csv),
             identity=str(settings.identity_csv))

    # ── Load CSVs ────────────────────────────────────────────────────────────
    log.info("loading case_pack")
    case_pack = pd.read_csv(settings.case_pack_csv, dtype={"flagged_txn_id": str})

    log.info("loading closed_cases")
    closed_cases = pd.read_csv(settings.closed_cases_csv)

    log.info("loading identity (may take a moment)")
    id_available = [c for c in IDENTITY_KEEP if c != "TransactionID"]
    identity_raw = pd.read_csv(settings.identity_csv, dtype={"TransactionID": str},
                                usecols=lambda c: c in IDENTITY_KEEP)

    log.info("loading transactions (may take several minutes for 590k rows)")
    txn_cols_available = None  # let pandas discover
    txn_raw = pd.read_csv(
        settings.transactions_csv,
        dtype={"TransactionID": str},
        usecols=lambda c: c in TXN_KEEP,
        low_memory=False,
    )
    log.info("transactions loaded", rows=len(txn_raw))

    # ── Derive card_id ───────────────────────────────────────────────────────
    txn = _derive_card_ids(txn_raw, case_pack, closed_cases)

    # ── Write to SQLite ───────────────────────────────────────────────────────
    log.info("writing investigation.db", path=str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Transactions
    txn.to_sql("transactions", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS txn_id_idx ON transactions(TransactionID)")
    conn.execute("CREATE INDEX IF NOT EXISTS txn_cust_idx ON transactions(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS txn_card_idx ON transactions(card_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS txn_ts_idx ON transactions(ts)")
    conn.commit()
    log.info("transactions written", rows=len(txn))

    # Identity
    identity_raw.to_sql("identity", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS id_txn_idx ON identity(TransactionID)")
    conn.commit()
    log.info("identity written", rows=len(identity_raw))

    # Closed cases
    closed_cases.to_sql("closed_cases", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS cc_cust_idx ON closed_cases(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS cc_card_idx ON closed_cases(card_id)")
    conn.commit()
    log.info("closed_cases written", rows=len(closed_cases))

    # Case pack
    case_pack.to_sql("case_pack", conn, if_exists="replace", index=False)
    conn.commit()
    log.info("case_pack written", rows=len(case_pack))

    # Summary counts
    conn.execute("""
    CREATE TABLE IF NOT EXISTS _meta AS
    SELECT
        (SELECT COUNT(*) FROM transactions) AS n_transactions,
        (SELECT COUNT(*) FROM identity) AS n_identity,
        (SELECT COUNT(*) FROM closed_cases) AS n_closed_cases,
        (SELECT COUNT(*) FROM case_pack) AS n_case_pack,
        datetime('now') AS prepared_at
    """)
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    log.info("prepare_data.complete", elapsed_s=round(elapsed, 1), db=str(db_path))


if __name__ == "__main__":
    prepare()
