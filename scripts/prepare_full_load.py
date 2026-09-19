"""
Full Dataset Loading Pipeline Preparation for TigerGraph Savanna Cloud (fraud_investigation).

DO NOT RUN AUTOMATICALLY: This script prepares and defines the full 590,742 transaction
data loading procedure. Execution requires explicit user approval.
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "full_load_staging"
DATA_DIR.mkdir(exist_ok=True, parents=True)


def export_full_dataset():
    """
    Exports all 590,742 transactions, cards, made edges, identity records,
    and closed cases from investigation.db into streaming CSV files.
    """
    import pandas as pd
    db_path = ROOT / "data" / "prepared" / "investigation.db"
    print(f"Opening SQLite database at {db_path}...")
    conn = sqlite3.connect(str(db_path))

    # 1. Cards
    print("Exporting cards...")
    cards_df = pd.read_sql("SELECT DISTINCT card_id, customer_id, card4, card6 FROM transactions", conn)
    cards_df["card4"] = cards_df["card4"].fillna("")
    cards_df["card6"] = cards_df["card6"].fillna("")
    cards_path = DATA_DIR / "full_cards.csv"
    cards_df.to_csv(cards_path, index=False)
    print(f"  Exported {len(cards_df):,} cards -> {cards_path}")

    # 2. Made edges
    print("Exporting MADE edges...")
    made_df = pd.read_sql("SELECT card_id, TransactionID FROM transactions", conn)
    made_path = DATA_DIR / "full_made.csv"
    made_df.to_csv(made_path, index=False)
    print(f"  Exported {len(made_df):,} MADE edges -> {made_path}")

    # 3. Transactions
    print("Exporting transactions...")
    txns_df = pd.read_sql("""
        SELECT TransactionID, ts, TransactionAmt, ProductCD,
               channel, addr1, addr2, risk_score,
               P_emaildomain, R_emaildomain, customer_id, card_id
        FROM transactions
    """, conn)
    txns_df["addr1"] = txns_df["addr1"].fillna("")
    txns_df["addr2"] = txns_df["addr2"].fillna("")
    txns_df["P_emaildomain"] = txns_df["P_emaildomain"].fillna("")
    txns_df["R_emaildomain"] = txns_df["R_emaildomain"].fillna("")
    txns_path = DATA_DIR / "full_transactions.csv"
    txns_df.to_csv(txns_path, index=False)
    print(f"  Exported {len(txns_df):,} transactions -> {txns_path}")

    # 4. Identity
    print("Exporting identity records...")
    id_df = pd.read_sql("""
        SELECT TransactionID, DeviceInfo, id_30, id_31, id_33, DeviceType
        FROM identity
    """, conn)
    id_df = id_df.fillna("unknown")
    id_path = DATA_DIR / "full_identity.csv"
    id_df.to_csv(id_path, index=False)
    print(f"  Exported {len(id_df):,} identity records -> {id_path}")

    # 5. Closed Cases
    print("Exporting closed cases...")
    cc_df = pd.read_sql("""
        SELECT case_id, customer_id, card_id, opened_at, closed_at,
               outcome, pattern, exposure_usd, n_txns, report_filed, analyst_notes
        FROM closed_cases
    """, conn)
    cc_df["report_filed"] = cc_df["report_filed"].apply(
        lambda x: "true" if str(x).lower() in ("yes", "true", "1") else "false"
    )
    cc_path = DATA_DIR / "full_closed_cases.csv"
    cc_df.to_csv(cc_path, index=False)
    print(f"  Exported {len(cc_df):,} closed cases -> {cc_path}")

    # 6. Verify case_pack
    cp_count = pd.read_sql("SELECT COUNT(*) AS cnt FROM case_pack", conn).iloc[0]["cnt"]
    print(f"  Verified case_pack benchmark count: {cp_count}")

    print("\nSource Counts Verification:")
    print(f"  transactions:        {len(txns_df):,} (expected 590,742) -> {'MATCH' if len(txns_df) == 590742 else 'MISMATCH'}")
    print(f"  identity:            {len(id_df):,} (expected 144,432) -> {'MATCH' if len(id_df) == 144432 else 'MISMATCH'}")
    print(f"  closed_cases_history:{len(cc_df):,} (expected 5,565) -> {'MATCH' if len(cc_df) == 5565 else 'MISMATCH'}")
    print(f"  case_pack:           {cp_count} (expected 20) -> {'MATCH' if cp_count == 20 else 'MISMATCH'}")

    conn.close()
    print("\nFull dataset staging complete.")


if __name__ == "__main__":
    export_full_dataset()
