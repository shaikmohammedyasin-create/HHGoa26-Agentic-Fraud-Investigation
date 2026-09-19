"""
Targeted Cleanup of Header Artifact Vertices from TigerGraph Savanna Cloud (fraud_investigation).

Deletes strictly the 8 literal CSV column-name header artifacts created by RESTPP
streaming file loads, bringing vertex and edge counts into exact 1:1 parity with
the underlying SQLite dataset.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

TARGET_ARTIFACTS = {
    "Transaction": ["TransactionID"],
    "Card": ["card_id"],
    "Customer": ["customer_id"],
    "ClosedCase": ["case_id"],
    "DeviceProfile": ["DeviceInfo | id_30 | id_31 | id_33"],
    "EmailDomain": ["P_emaildomain", "R_emaildomain"],
    "BillingRegion": ["addr1"]
}


def clean_header_artifacts():
    conn = get_conn()
    print("=" * 60)
    print("TARGETED CLEANUP OF CONFIRMED HEADER ARTIFACTS")
    print("=" * 60)

    # 1. Before Counts
    print("\n[BEFORE] Live Vertex Counts:")
    before_v = conn.getVertexCount("*")
    for k, v in sorted(before_v.items()):
        print(f"  {k:20}: {v:,}")

    before_e = {
        e: conn.getEdgeCount(e)
        for e in ["OWNS", "MADE", "MADE_BY", "FROM_DEVICE", "PURCHASER_EMAIL", "RECIPIENT_EMAIL", "BILLED_IN", "CC_ON_CARD"]
    }
    print("\n[BEFORE] Live Edge Counts:")
    for k, v in sorted(before_e.items()):
        print(f"  {k:20}: {v:,}")

    # 2. Deletion
    print("\n[CLEANUP] Deleting Confirmed Header Artifact Vertices:")
    deletion_results = {}
    for vtype, ids in TARGET_ARTIFACTS.items():
        try:
            del_cnt = conn.delVerticesById(vtype, ids)
            deletion_results[vtype] = {"ids": ids, "deleted": del_cnt}
            print(f"  Deleted from {vtype:16} IDs {ids}: count={del_cnt}")
        except Exception as ex:
            deletion_results[vtype] = {"ids": ids, "error": str(ex)}
            print(f"  ERROR deleting from {vtype} IDs {ids}: {ex}")

    # Allow TigerGraph graph engine a moment to update statistics
    time.sleep(3)

    # 3. After Counts
    print("\n[AFTER] Live Vertex Counts:")
    after_v = conn.getVertexCount("*")
    for k, v in sorted(after_v.items()):
        print(f"  {k:20}: {v:,}")

    after_e = {
        e: conn.getEdgeCount(e)
        for e in ["OWNS", "MADE", "MADE_BY", "FROM_DEVICE", "PURCHASER_EMAIL", "RECIPIENT_EMAIL", "BILLED_IN", "CC_ON_CARD"]
    }
    print("\n[AFTER] Live Edge Counts:")
    for k, v in sorted(after_e.items()):
        print(f"  {k:20}: {v:,}")

    # 4. Parity Check
    print("\n[PARITY CHECK AGAINST GROUND TRUTH]:")
    expected = {
        "Transaction": 590742,
        "Card": 14850,
        "ClosedCase": 5565,
        "OWNS": 14850,
        "MADE": 590742,
        "MADE_BY": 590742,
        "FROM_DEVICE": 144432,
        "CC_ON_CARD": 5565
    }
    all_match = True
    for ent, exp in expected.items():
        actual = after_v.get(ent) if ent in after_v else after_e.get(ent)
        matches = actual == exp
        if not matches:
            all_match = False
        print(f"  {ent:16}: actual={actual:,} vs expected={exp:,} -> {'EXACT MATCH' if matches else 'MISMATCH'}")

    print("\n" + "=" * 60)
    print(f"CLEANUP COMPLETE: {'ALL GROUND TRUTH COUNTS MATCH EXACTLY' if all_match else 'DISCREPANCY DETECTED'}")
    print("=" * 60)
    return {
        "before_v": before_v,
        "before_e": before_e,
        "deletion_results": deletion_results,
        "after_v": after_v,
        "after_e": after_e,
        "all_match": all_match
    }


if __name__ == "__main__":
    clean_header_artifacts()
