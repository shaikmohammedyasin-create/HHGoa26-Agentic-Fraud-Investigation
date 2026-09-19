import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()

print("=" * 60)
print("INSPECTING CANDIDATE HEADER ARTIFACT VERTICES")
print("=" * 60)

candidates = [
    ("Transaction", "TransactionID"),
    ("Card", "card_id"),
    ("Customer", "customer_id"),
    ("ClosedCase", "case_id"),
    ("DeviceProfile", "DeviceInfo | id_30 | id_31 | id_33"),
    ("EmailDomain", "P_emaildomain"),
    ("EmailDomain", "R_emaildomain"),
    ("BillingRegion", "addr1")
]

found_artifacts = {}

for v_type, candidate_id in candidates:
    res = conn.getVerticesById(v_type, candidate_id)
    if res:
        print(f"\n[FOUND] Vertex {v_type} with ID: '{candidate_id}'")
        print(f"  Attributes: {res[0].get('attributes')}")
        found_artifacts[v_type] = candidate_id

        # Inspect edges connected to this vertex
        for e_type in ["OWNS", "MADE", "MADE_BY", "FROM_DEVICE", "PURCHASER_EMAIL", "RECIPIENT_EMAIL", "BILLED_IN", "CC_ON_CARD"]:
            try:
                edges = conn.getEdges(v_type, candidate_id, e_type)
                if edges:
                    print(f"  Outgoing Edge {e_type}: {len(edges)} edge(s)")
                    for e in edges[:3]:
                        print(f"    -> to {e.get('to_type')} '{e.get('to_id')}' (attrs: {e.get('attributes')})")
            except Exception:
                pass
    else:
        print(f"[NOT FOUND] Vertex {v_type} with ID: '{candidate_id}'")

print("\n" + "=" * 60)
print("SUMMARY OF CANDIDATE HEADER ARTIFACTS FOUND:")
print(json.dumps(found_artifacts, indent=2))
print("=" * 60)
