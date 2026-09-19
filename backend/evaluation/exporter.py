"""
Export an InvestigationCase to the official answer-file JSON format
defined in README § Answer Format.

Output: one JSON file per case in cases/<case_id>.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.logging import get_logger
from backend.models import InvestigationCase

log = get_logger(__name__)


def case_to_answer(case: InvestigationCase) -> dict[str, Any]:
    """Map the internal rich case model to the graded answer schema."""
    return {
        "case_id": case.case_id,
        "case": {
            "status": case.status.value,
            "verdict": case.verdict.value,
            "fraud_probability": round(case.fraud_probability, 3),
            "pattern": case.pattern.value,
            "pattern_description": case.pattern_description,
            "affected_txn_ids": case.affected_txn_ids,
            "first_suspicious_txn_id": case.first_suspicious_txn_id,
            "connected_card_ids": case.connected_card_ids,
            "connected_device_profiles": case.connected_device_profiles,
            "exposure_usd": round(case.exposure_usd, 2),
            "evidence": [
                {
                    "claim": ev.claim,
                    "source": ev.source.value,
                    "ref": ev.ref,
                    "entity_ids": ev.entity_ids,
                }
                for ev in case.evidence
            ],
            "similar_prior_cases": case.similar_prior_cases,
            "summary": case.summary,
            "written_to_graph": case.written_to_graph,
            "graph_case_id": case.graph_case_id,
        },
        "evidence_requests": [
            {
                "type": er.type.value,
                "asked_after_step": er.asked_after_step,
                "assumed_response": er.assumed_response,
            }
            for er in case.evidence_requests
        ],
        "next_best_actions": {
            "initial": [
                {"action": a.action.value, "route": a.route.value, "reason": a.reason}
                for a in case.nba_initial
            ],
            "final": [
                {"action": a.action.value, "route": a.route.value, "reason": a.reason}
                for a in case.nba_final
            ],
            "what_changed": case.nba_what_changed,
        },
        "sar": {
            "file": case.sar.file,
            "reason": case.sar.reason,
            "narrative": case.sar.narrative,
            "subjects": case.sar.subjects,
            "total_amount_usd": round(case.sar.total_amount_usd, 2),
            "activity_dates": case.sar.activity_dates,
        },
        "stop_reason": case.stop_reason,
        "tool_calls": case.tool_calls,
        "tokens": case.tokens_used,
        "latency_s": case.latency_s,
    }


def write_answer_file(case: InvestigationCase, output_dir: Path | None = None) -> Path:
    """Write the answer JSON file and return the path."""
    out = output_dir or settings.cases_dir
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{case.case_id}.json"
    answer = case_to_answer(case)
    path.write_text(json.dumps(answer, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("exporter.written", path=str(path), case_id=case.case_id)
    return path
