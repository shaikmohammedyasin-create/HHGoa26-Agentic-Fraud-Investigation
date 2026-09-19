"""FastAPI application – backend API for the fraud investigation system."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.logging import configure_logging, get_logger
from backend import db as app_db
from backend.agents.orchestrator import run_investigation
from backend.evaluation.exporter import case_to_answer, write_answer_file
from backend.graph import query_router as graph

configure_logging()
log = get_logger(__name__)

app = FastAPI(
    title="HHGOA Fraud Investigation API",
    description="TigerGraph-native, evidence-grounded, policy-controlled agentic fraud investigation backend.",
    version="1.0.0",
)


# ─── Request / Response models ────────────────────────────────────────────────

class InvestigationRequest(BaseModel):
    case_id: str = Field(..., description="Case ID from case_pack.csv, e.g. HHG-001")


class InvestigationSummary(BaseModel):
    case_id: str
    state: str
    updated_at: str | None = None


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    approver: str = Field(..., min_length=1)


class EvidenceSubmission(BaseModel):
    type: str      # customer_validation | step_up_auth | analyst_info
    response: str


class HealthResponse(BaseModel):
    status: str
    graph: dict[str, str]
    app_db: str
    llm_provider: str
    app_env: str


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    graph_h = graph.health_check()
    try:
        app_db.get_db()
        db_status = "healthy"
    except Exception as exc:
        db_status = f"unavailable: {exc}"

    overall = "healthy"
    if isinstance(graph_h, dict):
        if any(v == "unavailable" for v in graph_h.values()):
            overall = "degraded"
    elif graph_h.get("status") == "unavailable":
        overall = "degraded"
    if db_status != "healthy":
        overall = "degraded"

    return HealthResponse(
        status=overall,
        graph=graph_h if isinstance(graph_h, dict) else {"local": graph_h.get("status", "?")},
        app_db=db_status,
        llm_provider=settings.llm_provider,
        app_env=settings.app_env,
    )


# ─── Investigations ──────────────────────────────────────────────────────────

@app.post("/investigations", tags=["Investigations"])
def create_investigation(
    req: InvestigationRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """Create and run a new investigation for a case-pack case."""
    if idempotency_key:
        existing = app_db.check_idempotency(idempotency_key)
        if existing:
            payload = app_db.load_investigation(existing)
            return case_to_answer(
                _reconstruct(payload)
            ) if payload else {"case_id": existing, "status": "exists"}

    try:
        case = run_investigation(req.case_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        log.exception("api.investigation.error", case_id=req.case_id)
        raise HTTPException(500, f"Investigation failed: {exc}")

    if idempotency_key:
        app_db.register_idempotency(idempotency_key, case.case_id)

    write_answer_file(case)
    return case_to_answer(case)


@app.get("/investigations", tags=["Investigations"])
def list_investigations(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return app_db.list_investigations(limit, offset)


@app.get("/investigations/{case_id}", tags=["Investigations"])
def get_investigation(case_id: str):
    payload = app_db.load_investigation(case_id)
    if payload is None:
        raise HTTPException(404, f"Case {case_id} not found")
    return case_to_answer(_reconstruct(payload))


@app.post("/investigations/{case_id}/run", tags=["Investigations"])
def run_investigation_endpoint(case_id: str):
    """Run or resume an investigation."""
    try:
        case = run_investigation(case_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    write_answer_file(case)
    return case_to_answer(case)


# ─── Evidence ────────────────────────────────────────────────────────────────

@app.get("/investigations/{case_id}/evidence", tags=["Evidence"])
def get_evidence(case_id: str):
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Case {case_id} not found")
    return payload.get("evidence", [])


@app.post("/investigations/{case_id}/evidence", tags=["Evidence"])
def submit_evidence(case_id: str, body: EvidenceSubmission):
    """Submit additional evidence (customer reply, analyst info)."""
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Case {case_id} not found")
    # In a full implementation this would trigger reassessment
    return {"status": "received", "case_id": case_id, "type": body.type}


# ─── Timeline / Audit ────────────────────────────────────────────────────────

@app.get("/investigations/{case_id}/timeline", tags=["Audit"])
def get_timeline(case_id: str):
    trail = app_db.get_audit_trail(case_id)
    if not trail:
        raise HTTPException(404, f"No audit trail for {case_id}")
    return trail


# ─── Approvals ────────────────────────────────────────────────────────────────

@app.get("/investigations/{case_id}/approvals", tags=["Approvals"])
def list_approvals(case_id: str):
    return app_db.list_pending_approvals(case_id)


@app.post("/investigations/{case_id}/approvals/{approval_id}", tags=["Approvals"])
def decide_approval(case_id: str, approval_id: str, body: ApprovalDecision):
    payload = app_db.load_approval(approval_id)
    if not payload:
        raise HTTPException(404, f"Approval {approval_id} not found")
    payload["status"] = body.decision
    payload["approver"] = body.approver
    payload["decided_at"] = datetime.utcnow().isoformat()
    app_db.save_approval(approval_id, case_id, payload)
    return payload


# ─── Cases (historical memory) ───────────────────────────────────────────────

@app.get("/cases/{case_id}", tags=["Case Memory"])
def get_case_memory(case_id: str):
    """Retrieve a closed historical case from the graph store."""
    from backend.graph.local_store import get_closed_cases_for_customer
    payload = app_db.load_investigation(case_id)
    if payload:
        return payload
    raise HTTPException(404, f"Case {case_id} not found in app state or graph")


# ─── Graph data ──────────────────────────────────────────────────────────────

@app.get("/graph/transaction/{txn_id}", tags=["Graph"])
def get_graph_transaction(txn_id: str):
    txn = graph.get_transaction(txn_id)
    if not txn:
        raise HTTPException(404, f"Transaction {txn_id} not found")
    return txn.model_dump(mode="json")


@app.get("/graph/card/{card_id}/history", tags=["Graph"])
def get_card_history(card_id: str, limit: int = Query(30, ge=1, le=100)):
    txns = graph.get_card_transaction_history(card_id, limit=limit)
    return [t.model_dump(mode="json") for t in txns]


@app.get("/graph/customer/{customer_id}/cards", tags=["Graph"])
def get_customer_cards(customer_id: str):
    return graph.get_customer_cards(customer_id)


@app.get("/graph/cases/customer/{customer_id}", tags=["Graph"])
def get_closed_cases(customer_id: str):
    cases = graph.get_closed_cases_for_customer(customer_id)
    return [c.model_dump(mode="json") for c in cases]


# ─── Benchmark ────────────────────────────────────────────────────────────────

@app.post("/benchmark/run", tags=["Evaluation"])
def run_benchmark():
    """Run the full 20-case benchmark (may take a while)."""
    from backend.evaluation.run_benchmark import run_all
    report = run_all()
    return report


@app.get("/benchmark/report", tags=["Evaluation"])
def get_benchmark_report():
    path = settings.cases_dir / "_benchmark_report.json"
    if not path.exists():
        raise HTTPException(404, "No benchmark report found. Run POST /benchmark/run first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _reconstruct(payload: dict) -> Any:
    """Reconstruct an InvestigationCase from stored JSON."""
    from backend.models import InvestigationCase
    return InvestigationCase(**payload)
