"""Verify new frontend API endpoints against real backend data."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

print("1. Testing GET /api/cases...")
r = client.get("/api/cases")
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
cases = r.json()
print(f"   Success: Retrieved {len(cases)} cases. First: {cases[0]['case_id']}")

print("2. Testing GET /api/investigations/HHG-001/full...")
r = client.get("/api/investigations/HHG-001/full")
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
full_case = r.json()
print(f"   Success: Case ID={full_case['case_id']}, Verdict={full_case['verdict']}, Pattern={full_case['pattern']}")
print(f"   Uncertainty items: {len(full_case.get('uncertainty', []))}")
print(f"   Evidence requests: {len(full_case.get('evidence_requests', []))}")
print(f"   Approvals: {len(full_case.get('approvals', []))}")

print("3. Testing GET /api/investigations/HHG-001/graph...")
r = client.get("/api/investigations/HHG-001/graph")
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
graph_data = r.json()
print(f"   Success: Nodes={len(graph_data['nodes'])}, Links={len(graph_data['links'])}")
for n in graph_data['nodes']:
    print(f"     Node: [{n['type']}] {n['label']}")

print("\nALL ADDITIVE FRONTEND APIS VERIFIED SUCCESSFULLY!")
