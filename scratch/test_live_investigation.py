import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force TigerGraph backend
os.environ["GRAPH_BACKEND"] = "tigergraph"

from backend.config import settings
from backend.agents.orchestrator import run_investigation

print("=" * 60)
print(f"RUNNING INVESTIGATION ON LIVE TIGERGRAPH GRAPH ({settings.graph_backend})")
print("=" * 60)

case = run_investigation("HHG-001", force=True)

print("\n--- CASE SUMMARY ---")
print(f"Case ID:            {case.case_id}")
print(f"Graph Backend:      {case.graph_backend}")
print(f"Verdict:            {case.verdict.value}")
print(f"Fraud Probability:  {case.fraud_probability:.3f}")
print(f"Pattern:            {case.pattern.value}")
print(f"Exposure USD:       ${case.exposure_usd:.2f}")
print(f"Evidence items:     {len(case.evidence)}")
print(f"Similar prior cases:{case.similar_prior_cases}")
print(f"Initial NBA:        {[a.action.value for a in case.nba_initial]}")
print(f"Final NBA:          {[a.action.value for a in case.nba_final]}")
print(f"What changed:       {case.nba_what_changed}")
print(f"SAR File:           {case.sar.file} (reason: {case.sar.reason})")
print(f"Written to graph:   {case.written_to_graph} (graph_case_id: {case.graph_case_id})")
print(f"Tool calls:         {case.tool_calls}")
print(f"Latency:            {case.latency_s}s")
print(f"\nSummary text:\n{case.summary}")
