import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn
from datetime import datetime

conn = get_conn()

print("=" * 60)
print("COMPREHENSIVE DATA INTEGRITY AND HEALTH AUDIT")
print("=" * 60)

# 1. Inspect Vertices for Malformed Values, Nulls, or Empty IDs
print("\n[CHECK 1] Sampling Transactions for Malformed Datetimes & Nulls:")
txns = conn.getVertices("Transaction", limit=20)
malformed_ts = 0
for t in txns:
    attrs = t.get("attributes", {})
    ts_str = attrs.get("ts")
    v_id = t.get("v_id")
    if not v_id or v_id == "":
        print("  ERROR: Empty transaction ID detected!")
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        malformed_ts += 1
        print(f"  ERROR: Malformed timestamp '{ts_str}' in txn {v_id}: {e}")
print(f"  Sampled {len(txns)} transactions: {malformed_ts} malformed timestamps.")

# 2. Inspect ClosedCase Datetimes
print("\n[CHECK 2] Sampling ClosedCases for Datetimes & Fields:")
cases = conn.getVertices("ClosedCase", limit=20)
malformed_cases = 0
for c in cases:
    attrs = c.get("attributes", {})
    v_id = c.get("v_id")
    opened_at = attrs.get("opened_at")
    closed_at = attrs.get("closed_at")
    try:
        dt1 = datetime.strptime(opened_at, "%Y-%m-%d %H:%M:%S")
        dt2 = datetime.strptime(closed_at, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        malformed_cases += 1
        print(f"  ERROR: Malformed case datetime in {v_id}: {e}")
print(f"  Sampled {len(cases)} cases: {malformed_cases} malformed datetimes.")

# 3. Inspect Customer Vertices & first_seen / last_seen
print("\n[CHECK 3] Inspecting Customer Vertices:")
custs = conn.getVertices("Customer", limit=20)
malformed_cust = 0
for cu in custs:
    attrs = cu.get("attributes", {})
    v_id = cu.get("v_id")
    f_seen = attrs.get("first_seen")
    try:
        dt = datetime.strptime(f_seen, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        malformed_cust += 1
print(f"  Sampled {len(custs)} customers: {malformed_cust} malformed first_seen.")

# 4. Check Edge Integrity & Directions
print("\n[CHECK 4] Checking Edge Directions:")
# OWNS: Customer -> Card
owns_edges = conn.getEdges("Customer", custs[0]["v_id"], "OWNS")
print(f"  OWNS edges from Customer {custs[0]['v_id']}: {len(owns_edges)}")
if owns_edges:
    print(f"    from_type: {owns_edges[0]['from_type']} -> to_type: {owns_edges[0]['to_type']} (Card: {owns_edges[0]['to_id']})")

# MADE: Card -> Transaction
card_id = owns_edges[0]['to_id'] if owns_edges else "C12382-K1"
made_edges = conn.getEdges("Card", card_id, "MADE")
print(f"  MADE edges from Card {card_id}: {len(made_edges)}")
if made_edges:
    print(f"    from_type: {made_edges[0]['from_type']} -> to_type: {made_edges[0]['to_type']} (Txn: {made_edges[0]['to_id']})")

# FROM_DEVICE: Transaction -> DeviceProfile
sample_txn = made_edges[0]['to_id'] if made_edges else "3514030"
dev_edges = conn.getEdges("Transaction", sample_txn, "FROM_DEVICE")
print(f"  FROM_DEVICE edges from Txn {sample_txn}: {len(dev_edges)}")

# CC_ON_CARD: ClosedCase -> Card
cc_edges = conn.getEdges("ClosedCase", cases[0]["v_id"], "CC_ON_CARD")
print(f"  CC_ON_CARD edges from ClosedCase {cases[0]['v_id']}: {len(cc_edges)}")
if cc_edges:
    print(f"    from_type: {cc_edges[0]['from_type']} -> to_type: {cc_edges[0]['to_type']} (Card: {cc_edges[0]['to_id']})")

print("\n" + "=" * 60)
print("AUDIT COMPLETE")
print("=" * 60)
