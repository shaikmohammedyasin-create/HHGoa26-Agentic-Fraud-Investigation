import os
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure TigerGraph backend
os.environ["GRAPH_BACKEND"] = "tigergraph"

from backend.config import settings
from backend.agents.orchestrator import run_investigation

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

cases_to_test = [
    ("HHG-006", "Obvious Fraud (Critical Risk / High Probability / SAR Filed / L1+L2 Approvals)"),
    ("HHG-001", "Ambiguous / Insufficient Evidence (Borderline / Customer Validation No Response)"),
    ("HHG-003", "Additional Evidence Changes Recommendation (Customer Confirms Travel -> CLOSE_NO_FRAUD)"),
]

print("=" * 70)
print(f"TESTING 3 REPRESENTATIVE CASES ON LIVE TIGERGRAPH ({settings.graph_backend})")
print("=" * 70)

results = {}

for case_id, description in cases_to_test:
    print(f"\n>>> Running Case: {case_id} — {description}")
    start_t = time.time()
    try:
        case = run_investigation(case_id, force=True)
        dur = time.time() - start_t
        results[case_id] = {
            "description": description,
            "verdict": case.verdict.value,
            "fraud_probability": round(case.fraud_probability, 3),
            "pattern": case.pattern.value,
            "exposure_usd": case.exposure_usd,
            "evidence_count": len(case.evidence),
            "evidence_items": [
                {"claim": e.claim, "source": e.source.value, "ref": e.ref, "entity_ids": e.entity_ids}
                for e in case.evidence
            ],
            "initial_nba": [{"action": a.action.value, "route": a.route.value, "reason": a.reason} for a in case.nba_initial],
            "final_nba": [{"action": a.action.value, "route": a.route.value, "reason": a.reason} for a in case.nba_final],
            "what_changed": case.nba_what_changed,
            "sar_file": case.sar.file,
            "sar_reason": case.sar.reason,
            "sar_narrative": case.sar.narrative,
            "stop_reason": case.stop_reason,
            "written_to_graph": case.written_to_graph,
            "graph_case_id": case.graph_case_id,
            "tool_calls": case.tool_calls,
            "latency_s": round(dur, 2),
            "summary": case.summary,
        }
        print(f"  [SUCCESS] {case_id}: verdict={case.verdict.value}, prob={case.fraud_probability:.3f}, final_nba={[a.action.value for a in case.nba_final]}, written_to_graph={case.written_to_graph} ({case.graph_case_id})")
    except Exception as exc:
        print(f"  [ERROR] {case_id}: {exc}")
        import traceback
        traceback.print_exc()

out_path = ROOT / "scratch" / "benchmark_3_cases_live_report.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\n" + "=" * 70)
print(f"SAVED 3 CASES REPORT TO: {out_path}")
print("=" * 70)
