import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

def with_retry(fn, max_retries=4, delay=2):
    for i in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if i == max_retries:
                raise e
            time.sleep(delay)

conn = with_retry(get_conn)

# Test creating a test InvestigationCase
test_case_id = "CASE-2016-TEST-001"
v_data = [
    (test_case_id, {
        "trigger_type": "risk_score",
        "trigger_text": "High risk test transaction",
        "opened_at": "2016-12-04 19:55:28",
        "status": "open",
        "verdict": "uncertain",
        "fraud_probability": 0.45,
        "pattern": "none",
        "exposure_usd": 77.07,
        "summary": "Test investigation summary."
    })
]
print("Testing upsertVertices for InvestigationCase...")
res_v = conn.upsertVertices("InvestigationCase", v_data)
print("  upsertVertices res:", res_v)

# Test upsertEdges for IC_ON_CARD
e_data = [
    (test_case_id, "C12382-K1", {})
]
print("Testing upsertEdges for IC_ON_CARD...")
res_e = conn.upsertEdges("InvestigationCase", "IC_ON_CARD", "Card", e_data)
print("  upsertEdges res:", res_e)

# Verify vertex exists
v_check = conn.getVerticesById("InvestigationCase", test_case_id)
print("  getVerticesById:", v_check)

# Clean up test vertex
print("Cleaning up test vertex...")
del_res = conn.delVerticesById("InvestigationCase", [test_case_id])
print("  Deleted count:", del_res)
