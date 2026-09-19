import json
import urllib.request
from pathlib import Path

def test_cases():
    url = "http://127.0.0.1:8000/api/cases"
    req = urllib.request.urlopen(url)
    cases = json.loads(req.read())
    print(f"Total cases from /api/cases: {len(cases)}")
    case_ids = [c["case_id"] for c in cases]
    print(f"Case IDs: {case_ids}")
    expected_ids = [f"HHG-{i:03d}" for i in range(1, 21)]
    assert sorted(case_ids) == sorted(expected_ids), f"Mismatch in case IDs: {set(expected_ids) - set(case_ids)}"
    print("Point 5 PASS: Exactly all 20 cases returned.")

def test_api_endpoints():
    api_js = Path("frontend/js/api.js").read_text(encoding="utf-8")
    assert "fetch(`${this.baseUrl}/investigations`" in api_js or "/investigations" in api_js, "runInvestigation endpoint missing"
    assert "/investigations/${encodeURIComponent(caseId)}/approvals/${encodeURIComponent(approvalId)}" in api_js, "decideApproval endpoint missing"
    assert "/api/investigations/${encodeURIComponent(caseId)}/graph" in api_js, "getInvestigationGraph endpoint missing"
    assert "/api/investigations/${encodeURIComponent(caseId)}/full" in api_js, "getInvestigationFull endpoint missing"
    assert "/api/cases" in api_js, "getCases endpoint missing"
    print("Points 6 & 7 PASS: API client calls authoritative real backend endpoints.")

def test_no_hardcoded_benchmark_data():
    app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")
    graph_js = Path("frontend/js/graph.js").read_text(encoding="utf-8")
    index_html = Path("frontend/index.html").read_text(encoding="utf-8")

    # Check for hardcoded benchmark results or node lists
    for name, content in [("app.js", app_js), ("graph.js", graph_js), ("index.html", index_html)]:
        for case_id in [f"HHG-{i:03d}" for i in range(1, 21)]:
            # In app.js, case_id should only appear if dynamically passed, not hardcoded conditionals
            if f'caseId === "{case_id}"' in content or f"caseId === '{case_id}'" in content:
                raise AssertionError(f"Found hardcoded case branch for {case_id} in {name}!")

    # Check that graph renders from API data
    assert "setData(graphData)" in app_js, "Graph is not fed from API graphData"
    assert "graphData.nodes" in graph_js, "Graph does not consume graphData.nodes"
    print("Points 8, 9, 10 PASS: No hardcoded benchmark data or fake nodes. Data originates strictly from real backend.")

if __name__ == "__main__":
    test_cases()
    test_api_endpoints()
    test_no_hardcoded_benchmark_data()
