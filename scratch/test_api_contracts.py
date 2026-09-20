"""
API Contract Verification Script for Pre-Demo Technical Freeze Audit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_contracts():
    print("Testing API contracts...")
    
    # 1. Health
    r = client.get("/health")
    assert r.status_code == 200, f"/health failed: {r.status_code}"
    print("  GET /health -> 200 OK")

    # 2. Root static frontend
    r = client.get("/")
    assert r.status_code == 200, f"/ failed: {r.status_code}"
    assert "<!DOCTYPE html>" in r.text
    print("  GET / -> 200 OK")

    # 3. Case Pack triggers
    r = client.get("/api/cases")
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 20
    print(f"  GET /api/cases -> 200 OK ({len(cases)} cases)")

    # 4. Full investigation
    r = client.get("/api/investigations/HHG-001/full")
    assert r.status_code == 200
    data = r.json()
    assert data["case_id"] == "HHG-001"
    assert "evidence" in data
    assert "uncertainty" in data
    assert "nba_final" in data
    print("  GET /api/investigations/HHG-001/full -> 200 OK")

    # 5. Graph subgraph
    r = client.get("/api/investigations/HHG-001/graph")
    assert r.status_code == 200
    g = r.json()
    assert "nodes" in g and "links" in g
    print(f"  GET /api/investigations/HHG-001/graph -> 200 OK ({len(g['nodes'])} nodes, {len(g['links'])} links)")

    # 6. List investigations
    r = client.get("/investigations")
    assert r.status_code == 200
    inv_list = r.json()
    print(f"  GET /investigations -> 200 OK ({len(inv_list)} investigations)")

    # 7. Single investigation answer format
    r = client.get("/investigations/HHG-001")
    assert r.status_code == 200
    ans = r.json()
    assert "case" in ans and "next_best_actions" in ans
    print("  GET /investigations/HHG-001 -> 200 OK")

    # 8. Not-found behavior
    r = client.get("/investigations/NON_EXISTENT_9999")
    assert r.status_code == 404
    print("  GET /investigations/NON_EXISTENT -> 404 OK")

    # 9. Evidence endpoint
    r = client.get("/investigations/HHG-001/evidence")
    assert r.status_code == 200
    evs = r.json()
    print(f"  GET /investigations/HHG-001/evidence -> 200 OK ({len(evs)} items)")

    # 10. Timeline endpoint
    r = client.get("/investigations/HHG-001/timeline")
    assert r.status_code == 200
    tl = r.json()
    print(f"  GET /investigations/HHG-001/timeline -> 200 OK ({len(tl)} events)")

    # 11. Approvals endpoint
    r = client.get("/investigations/HHG-001/approvals")
    assert r.status_code == 200
    aprs = r.json()
    print(f"  GET /investigations/HHG-001/approvals -> 200 OK ({len(aprs)} records)")

    print("\nALL 11 API CONTRACT CHECKS PASSED!")

if __name__ == "__main__":
    test_contracts()
