import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)
r = client.get("/api/investigations/HHG-001/full")
data = r.json()

print(f"Case ID: {data.get('case_id')}")
print(f"Status: {data.get('status')}")
print(f"Verdict: {data.get('verdict')}")
print(f"Fraud Probability: {data.get('fraud_probability')}")
print(f"Pattern Primary: {data.get('pattern')}")
print(f"Pattern Secondary: {data.get('pattern_secondary')}")
print(f"Pattern Candidates: {data.get('pattern_candidates')}")
print(f"Evidence Count: {len(data.get('evidence', []))}")

for i, ev in enumerate(data.get("evidence", [])):
    cid = ev.get("evidence_id")
    ctype = ev.get("claim_type")
    src = ev.get("source")
    qry = ev.get("originating_query")
    claim = ev.get("claim", "")[:60]
    print(f"  [{i}] ID={cid} | Type={ctype} | Source={src} | Query={qry} | Claim={claim}")

def safe_print(s):
    print(str(s).encode('ascii', errors='replace').decode('ascii'))

safe_print(f"Uncertainty: {data.get('uncertainty')}")

print(f"NBA Initial: {data.get('nba_initial')}")
print(f"NBA Final: {data.get('nba_final')}")
print(f"NBA What Changed: {data.get('nba_what_changed')}")
print(f"Approvals Count: {len(data.get('approvals', []))}")
for i, apr in enumerate(data.get("approvals", [])[:3]):
    print(f"  Approval [{i}]: action={apr.get('action_type')} status={apr.get('status')} level={apr.get('approval_level')}")

print("\n--- GRAPH ENDPOINT TEST ---")
rg = client.get("/api/investigations/HHG-001/graph")
gdata = rg.json()
print(f"Graph nodes count: {len(gdata.get('nodes', []))}")
print(f"Graph edges count: {len(gdata.get('edges', []))}")
for n in gdata.get("nodes", [])[:3]:
    print(f"  Node: id={n.get('id')} type={n.get('type')} label={n.get('label')}")
for e in gdata.get("edges", [])[:3]:
    print(f"  Edge: src={e.get('source')} dst={e.get('target')} type={e.get('type')}")
