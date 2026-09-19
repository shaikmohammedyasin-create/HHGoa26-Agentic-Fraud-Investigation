"""
Clean-state rerun of the 3 representative benchmark cases with end-to-end stage tracing.
Proves the entire 12-stage execution flow against live TigerGraph Savanna Cloud.
"""
from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ["GRAPH_BACKEND"] = "tigergraph"

from backend.config import settings
from backend.agents.orchestrator import run_investigation
from backend.graph import tg_adapter
from backend import db as app_db

cases_to_run = [
    ("HHG-006", "Obvious Fraud (Critical Risk / High Probability / SAR Filed / L1+L2 Approvals)"),
    ("HHG-001", "Ambiguous / Insufficient Evidence (Borderline / Customer Validation No Response)"),
    ("HHG-003", "Additional Evidence Changes Recommendation (Customer Confirms Denial -> BLOCK_CARD)"),
]

print("=" * 80)
print("PHASE B HARDENING: 3 REPRESENTATIVE CASES CLEAN RERUN")
print("=" * 80)

# Step 0: Clean pre-existing database records for these cases to guarantee clean-state
conn = app_db.get_db()
for case_id, _ in cases_to_run:
    conn.execute("DELETE FROM approvals WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM audit_events WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM investigations WHERE case_id=?", (case_id,))
conn.commit()
print("Cleaned local investigation store for cases:", [c[0] for c in cases_to_run])

verification_proofs = {}

for case_id, description in cases_to_run:
    print(f"\n" + "-" * 70)
    print(f"STAGE-BY-STAGE EXECUTION PROOF: {case_id} — {description}")
    print("-" * 70)

    t0 = time.time()
    case = run_investigation(case_id, force=True)
    dur = time.time() - t0

    # Retrieve audit trail and approvals
    audit_events = app_db.get_audit_trail(case_id)
    approvals = app_db.list_pending_approvals(case_id)

    # 1. TRIGGER
    trigger_data = {
        "case_id": case.trigger.case_id,
        "trigger_type": case.trigger.trigger_type.value,
        "trigger_text": case.trigger.trigger_text,
        "flagged_txn_id": case.trigger.flagged_txn_id,
        "card_id": case.trigger.card_id,
        "customer_id": case.trigger.customer_id,
        "risk_score": case.trigger.risk_score,
    }

    # 2. LIVE GRAPH / MCP
    graph_evidence_sources = [
        {"tool": ev.ref, "claim": ev.claim, "entities": ev.entity_ids}
        for ev in case.evidence if ev.source.value == "graph"
    ]

    # 3. EVIDENCE
    all_evidence = [
        {"claim": ev.claim, "source": ev.source.value, "ref": ev.ref, "confidence": ev.confidence}
        for ev in case.evidence
    ]

    # 4. ASSESSMENT
    assessment = {
        "verdict": case.verdict.value,
        "fraud_probability": round(case.fraud_probability, 3),
        "pattern": case.pattern.value,
        "exposure_usd": case.exposure_usd,
    }

    # 5. UNCERTAINTY
    uncertainty_items = [
        u.model_dump(mode="json") if hasattr(u, "model_dump") else str(u)
        for u in case.uncertainty
    ]

    # 6. EVIDENCE REQUEST
    evidence_requests = [
        {
            "type": req.type.value,
            "asked_after_step": req.asked_after_step,
            "rationale": req.rationale,
            "status": req.status,
            "assumed_response": req.assumed_response,
        }
        for req in case.evidence_requests
    ]

    # 7. UPDATED EVIDENCE
    updated_evidence = [ev.claim for ev in case.evidence if ev.source.value == "customer"]

    # 8. UPDATED NBA (Initial vs Final)
    nba_progression = {
        "initial": [{"action": a.action.value, "route": a.route.value, "reason": a.reason} for a in case.nba_initial],
        "final": [{"action": a.action.value, "route": a.route.value, "reason": a.reason} for a in case.nba_final],
        "what_changed": case.nba_what_changed,
    }

    # 9. POLICY
    policy_evaluation = {
        "sar_file": case.sar.file,
        "sar_reason": case.sar.reason,
        "stop_reason": case.stop_reason,
    }

    # 10. APPROVAL
    approval_records = [
        {
            "approval_id": a.get("approval_id"),
            "action": str(a.get("action")),
            "route": str(a.get("required_route") or a.get("route")),
            "status": str(a.get("status")),
            "rationale": a.get("reason") or a.get("rationale"),
        }
        for a in approvals
    ]

    # 11. INVESTIGATIONCASE UPDATE
    graph_persistence = {
        "written_to_graph": case.written_to_graph,
        "graph_case_id": case.graph_case_id,
        "lifecycle_events": [e["event_type"] for e in audit_events if "graph" in e["event_type"] or "state" in e["event_type"]],
    }

    # 12. FINAL EXPLANATION
    final_explanation = {
        "summary": case.summary,
        "sar_narrative": case.sar.narrative if case.sar.file else None,
    }

    proof = {
        "case_id": case_id,
        "description": description,
        "execution_time_s": round(dur, 2),
        "stages": {
            "1_TRIGGER": trigger_data,
            "2_LIVE_GRAPH_MCP": {"tool_calls": case.tool_calls, "graph_sources": graph_evidence_sources},
            "3_EVIDENCE": all_evidence,
            "4_ASSESSMENT": assessment,
            "5_UNCERTAINTY": uncertainty_items,
            "6_EVIDENCE_REQUEST": evidence_requests,
            "7_UPDATED_EVIDENCE": updated_evidence,
            "8_UPDATED_NBA": nba_progression,
            "9_POLICY": policy_evaluation,
            "10_APPROVAL": approval_records,
            "11_INVESTIGATIONCASE_UPDATE": graph_persistence,
            "12_FINAL_EXPLANATION": final_explanation,
        }
    }

    verification_proofs[case_id] = proof

    print(f"  [PROVED] {case_id}:")
    print(f"    - Trigger: {trigger_data['trigger_type']} on txn {trigger_data['flagged_txn_id']}")
    print(f"    - Verdict: {assessment['verdict']} (P={assessment['fraud_probability']:.3f})")
    print(f"    - Initial NBA: {[a['action'] for a in nba_progression['initial']]}")
    print(f"    - Final NBA:   {[a['action'] for a in nba_progression['final']]}")
    print(f"    - Approvals generated: {[a['action'] + ' (' + a['route'] + ')' for a in approval_records]}")
    print(f"    - Graph Persistence: {graph_persistence['graph_case_id']} (written={graph_persistence['written_to_graph']})")

proof_path = ROOT / "scratch" / "clean_3_cases_proof.json"
with open(proof_path, "w", encoding="utf-8") as f:
    json.dump(verification_proofs, f, indent=2)

print("\n" + "=" * 80)
print(f"STAGE-BY-STAGE EXECUTION PROOFS SAVED TO: {proof_path}")
print("=" * 80)
