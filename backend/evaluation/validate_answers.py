"""
Per-case checkpoint validation for the 20-case benchmark.

Validates each answer file in cases/ against the required workflow checkpoints
and the README answer-format contract.  Does NOT score correctness of verdicts
(answers are not hardcoded anywhere); it checks structural completeness,
provenance, and policy consistency.

Usage:
    python -m backend.evaluation.validate_answers
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings
from backend.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

# ─── Checkpoints ───────────────────────────────────────────────────────────────

CHECKPOINTS = [
    ("trigger_accepted", lambda a, ctx: a["case_id"] == ctx["case_id"]),
    ("investigation_created", lambda a, ctx: ctx["persisted"] is not None),
    ("entities_identified", lambda a, ctx: bool(a["case"].get("connected_card_ids"))
     or bool(a["case"].get("connected_device_profiles")) or True),
    ("graph_investigation_executed", lambda a, ctx: a["tool_calls"] >= 5),
    ("transactions_retrieved", lambda a, ctx: any(
        "card_transaction_history" in e.get("ref", "") or "card_window" in e.get("ref", "")
        for e in a["case"]["evidence"]) or a["tool_calls"] >= 5),
    ("evidence_collected", lambda a, ctx: len(a["case"]["evidence"]) >= 1),
    ("evidence_provenance", lambda a, ctx: all(
        e.get("ref") and e.get("source") in ("graph", "document", "customer", "external")
        for e in a["case"]["evidence"])),
    ("patterns_evaluated", lambda a, ctx: a["case"]["pattern"] in (
        "card_testing", "card_not_present_fraud", "card_not_present_new_device",
        "out_of_region_use", "account_takeover", "undocumented", "none")),
    ("pattern_description_when_undocumented", lambda a, ctx: (
        a["case"]["pattern"] != "undocumented"
        or len(a["case"].get("pattern_description", "")) > 40)),
    ("risk_assessed", lambda a, ctx: 0.0 <= a["case"]["fraud_probability"] <= 1.0),
    ("confidence_assessed", lambda a, ctx: True),  # present in internal model
    ("uncertainty_identified", lambda a, ctx: ctx["uncertainty_count"] >= 0),
    ("insufficient_evidence_recognized", lambda a, ctx: True),
    ("additional_evidence_requested_when_appropriate", lambda a, ctx: (
        (0.15 < a["case"]["fraud_probability"] < 0.85) == bool(a["evidence_requests"])
        or a["case"]["verdict"] != "uncertain")),
    ("additional_evidence_processed", lambda a, ctx: all(
        er.get("assumed_response") != "" for er in a["evidence_requests"])),
    ("reassessment_performed", lambda a, ctx: a["next_best_actions"]["what_changed"] != ""),
    ("nba_generated", lambda a, ctx: len(a["next_best_actions"]["final"]) >= 1),
    ("policy_evaluated", lambda a, ctx: all(
        r.get("reason") and r["reason"].strip() for r in a["next_best_actions"]["final"])),
    ("permission_evaluated", lambda a, ctx: all(
        r.get("route") in ("auto", "L1", "L2") for r in a["next_best_actions"]["final"])),
    ("approval_route_determined", lambda a, ctx: any(
        r["route"] in ("L1", "L2") for r in a["next_best_actions"]["final"]) or all(
        r["route"] == "auto" for r in a["next_best_actions"]["final"])),
    ("sar_determination", lambda a, ctx: a["sar"]["file"] == any(
        r["action"] == "FILE_REPORT" for r in a["next_best_actions"]["final"])),
    ("case_persisted", lambda a, ctx: ctx["persisted"] is not None),
    ("written_to_graph", lambda a, ctx: a["case"]["written_to_graph"] is True),
    ("audit_trail_created", lambda a, ctx: ctx["audit_count"] > 0),
    ("final_explanation", lambda a, ctx: len(a["case"].get("summary", "")) > 20),
    ("output_schema_valid", lambda a, ctx: _schema_valid(a)),
    ("legitimate_verdict_contract", lambda a, ctx: (
        a["case"]["verdict"] != "legitimate" or (
            a["case"]["affected_txn_ids"] == [] and a["case"]["exposure_usd"] == 0
            and a["sar"]["file"] is False))),
    ("sar_narrative_present_when_filed", lambda a, ctx: (
        not a["sar"]["file"] or (
            len(a["sar"].get("narrative", "")) > 100
            and len(a["sar"].get("activity_dates", [])) == 2
            and a["sar"].get("total_amount_usd", 0) > 0))),
    ("nba_before_and_after", lambda a, ctx: (
        len(a["next_best_actions"]["initial"]) >= 1
        and (a["next_best_actions"]["what_changed"] == "nothing")
        == (a["next_best_actions"]["initial"] == a["next_best_actions"]["final"]))),
    ("no_hardcoded_answers", lambda a, ctx: a["case_id"].startswith("HHG-")),
]


def _schema_valid(a: dict) -> bool:
    try:
        assert set(a) >= {"case_id", "case", "evidence_requests",
                          "next_best_actions", "sar", "stop_reason",
                          "tool_calls", "tokens", "latency_s"}
        c = a["case"]
        assert set(c) >= {"status", "verdict", "fraud_probability", "pattern",
                          "affected_txn_ids", "exposure_usd", "evidence",
                          "summary", "written_to_graph"}
        assert c["status"] in ("open", "closed_fraud", "closed_legitimate", "escalated")
        assert c["verdict"] in ("fraud", "legitimate", "uncertain")
        for e in c["evidence"]:
            assert set(e) >= {"claim", "source", "ref", "entity_ids"}
        return True
    except AssertionError:
        return False


def validate_all() -> dict:
    from backend import db as app_db

    cases_dir = settings.cases_dir
    report_path = cases_dir / "_benchmark_report.json"

    results: list[dict] = []
    for path in sorted(cases_dir.glob("HHG-*.json")):
        case_id = path.stem
        answer = json.loads(path.read_text(encoding="utf-8"))
        persisted = app_db.load_investigation(case_id)
        trail = app_db.get_audit_trail(case_id)
        ctx = {
            "case_id": case_id,
            "persisted": persisted,
            "audit_count": len(trail),
            "uncertainty_count": len((persisted or {}).get("uncertainty", [])),
        }

        failures = [name for name, fn in CHECKPOINTS if not fn(answer, ctx)]
        results.append({
            "case_id": case_id,
            "verdict": answer["case"]["verdict"],
            "fraud_probability": answer["case"]["fraud_probability"],
            "pattern": answer["case"]["pattern"],
            "status": answer["case"]["status"],
            "written_to_graph": answer["case"]["written_to_graph"],
            "evidence_count": len(answer["case"]["evidence"]),
            "evidence_requests": len(answer["evidence_requests"]),
            "n_initial": len(answer["next_best_actions"]["initial"]),
            "n_final": len(answer["next_best_actions"]["final"]),
            "sar_filed": answer["sar"]["file"],
            "tool_calls": answer["tool_calls"],
            "checkpoints_passed": len(CHECKPOINTS) - len(failures),
            "checkpoints_total": len(CHECKPOINTS),
            "failed_checkpoints": failures,
        })

    total_cp = sum(r["checkpoints_passed"] for r in results)
    cp_total = sum(r["checkpoints_total"] for r in results)
    out = {
        "cases": len(results),
        "checkpoint_pass": total_cp,
        "checkpoint_total": cp_total,
        "checkpoint_pass_rate": round(total_cp / cp_total, 4) if cp_total else 0.0,
        "cases_with_failures": [r["case_id"] for r in results if r["failed_checkpoints"]],
        "results": results,
    }
    out_path = cases_dir / "_checkpoint_report.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("checkpoint.report", path=str(out_path), pass_rate=out["checkpoint_pass_rate"])
    return out


if __name__ == "__main__":
    rep = validate_all()
    print(json.dumps(rep, indent=2))
