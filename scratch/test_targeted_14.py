import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["STRICT_GRAPH_BACKEND"] = "1"
os.environ["GRAPH_BACKEND"] = "tigergraph"

from backend.config import settings
settings.strict_graph_backend = True
settings.graph_backend = "tigergraph"

from backend.agents.orchestrator import run_investigation

TARGETED_CASES = [
    "HHG-004", "HHG-005", "HHG-006", "HHG-008", "HHG-009",
    "HHG-010", "HHG-011", "HHG-013", "HHG-014", "HHG-015",
    "HHG-016", "HHG-017", "HHG-019", "HHG-020"
]

def main():
    print("=" * 70)
    print("TARGETED REGRESSION: 14 CASES PREVIOUSLY FAILING ON device_neighbors")
    print("MODE: STRICT_GRAPH_BACKEND=1 (LIVE TIGERGRAPH SAVANNA)")
    print("=" * 70)
    
    results = {}
    errors = {}
    
    for case_id in TARGETED_CASES:
        print(f"\nRunning {case_id}...", flush=True)
        try:
            case = run_investigation(case_id, force=True)
            results[case_id] = {
                "status": case.status.value,
                "verdict": case.verdict.value,
                "probability": case.fraud_probability,
                "pattern": case.pattern.value if case.pattern else "none",
                "evidence_count": len(case.evidence),
                "device_profiles": case.connected_device_profiles,
                "similar_prior_cases": case.similar_prior_cases,
                "written_to_graph": case.written_to_graph,
                "actions": [a.action for a in case.nba_final] if case.nba_final else [],
                "sar_file": case.sar.file if case.sar else False,
            }
            print(f"  SUCCESS -> Verdict={case.verdict.value}, Prob={case.fraud_probability:.2f}, Pattern={case.pattern.value}, Evidence={len(case.evidence)}, WrittenToGraph={case.written_to_graph}")
        except Exception as exc:
            import traceback
            errors[case_id] = str(exc)
            print(f"  FAILED -> {exc}")
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"TARGETED SUMMARY: {len(results)} SUCCEEDED, {len(errors)} FAILED OUT OF {len(TARGETED_CASES)}")
    print("=" * 70)
    if errors:
        print("Errors encountered:")
        for cid, err in errors.items():
            print(f"  {cid}: {err}")

if __name__ == "__main__":
    main()
