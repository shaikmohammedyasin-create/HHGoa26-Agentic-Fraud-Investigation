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


# ─── Frontend & Enhanced API Endpoints ────────────────────────────────────────

@app.get("/api/cases", tags=["Case Pack"])
def get_case_pack_triggers():
    """List all 20 benchmark case triggers from the case pack."""
    triggers = graph.get_all_case_triggers()
    return triggers


@app.get("/api/investigations/{case_id}/full", tags=["Investigations"])
def get_full_investigation(case_id: str):
    """Retrieve complete rich investigation model including trigger, uncertainty, approvals."""
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Investigation for case {case_id} not found")
    return payload


@app.get("/api/investigations/{case_id}/graph", tags=["Graph Visualization"])
def get_investigation_subgraph(case_id: str):
    """Build a case-scoped local knowledge subgraph for visual rendering."""
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Investigation for case {case_id} not found")

    nodes = []
    links = []
    seen_nodes = set()

    def add_node(node_id: str, label: str, node_type: str, metadata: dict[str, Any] | None = None):
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({
            "id": node_id,
            "label": label,
            "type": node_type,
            "metadata": metadata or {},
        })

    def add_link(source: str, target: str, rel_type: str):
        if not source or not target:
            return
        links.append({
            "source": source,
            "target": target,
            "type": rel_type,
        })

    # Subject Customer & Card
    cust_id = payload.get("customer_id") or (payload.get("trigger") or {}).get("customer_id")
    card_id = payload.get("card_id") or (payload.get("trigger") or {}).get("card_id")
    flagged_txn_id = payload.get("flagged_txn_id") or (payload.get("trigger") or {}).get("flagged_txn_id")

    if cust_id:
        add_node(cust_id, f"Customer: {cust_id}", "Customer", {"customer_id": cust_id})
    if card_id:
        add_node(card_id, f"Card: {card_id}", "Card", {"card_id": card_id})
    if cust_id and card_id:
        add_link(cust_id, card_id, "OWNS")

    # Flagged Transaction
    if flagged_txn_id:
        trigger_meta = payload.get("trigger") or {}
        add_node(
            flagged_txn_id,
            f"Flagged Txn: #{flagged_txn_id}",
            "FlaggedTransaction",
            {
                "txn_id": flagged_txn_id,
                "amount": trigger_meta.get("amount") or payload.get("exposure_usd"),
                "risk_score": trigger_meta.get("risk_score"),
                "is_flagged": True,
            }
        )
        if card_id:
            add_link(card_id, flagged_txn_id, "MADE")

    # Connected / Affected Transactions
    for txn_id in payload.get("affected_txn_ids", []):
        t_id = str(txn_id)
        if t_id != flagged_txn_id:
            add_node(t_id, f"Txn: #{t_id}", "Transaction", {"txn_id": t_id, "affected": True})
            if card_id:
                add_link(card_id, t_id, "MADE")

    # Connected Device Profiles
    for dp in payload.get("connected_device_profiles", []):
        if dp:
            dp_id = f"DEV-{dp[:32]}"
            add_node(dp_id, f"Device: {dp[:28]}...", "DeviceProfile", {"full_device": dp})
            if flagged_txn_id:
                add_link(flagged_txn_id, dp_id, "FROM_DEVICE")

    # Connected Cards (e.g. from shared devices or multi-card fraud)
    for c_id in payload.get("connected_card_ids", []):
        if c_id and c_id != card_id:
            add_node(c_id, f"Connected: {c_id}", "ConnectedCard", {"card_id": c_id})

    # Closed Cases (Historical memory links)
    for cc_id in payload.get("similar_prior_cases", [])[:5]:
        add_node(cc_id, f"Prior Case: {cc_id}", "ClosedCase", {"case_id": cc_id})
        if cust_id:
            add_link(cc_id, cust_id, "CC_ON_CUSTOMER")
        if card_id:
            add_link(cc_id, card_id, "CC_ON_CARD")

    # Active Investigation Case (Persisted graph memory)
    graph_case_id = payload.get("graph_case_id") or f"CASE-2016-{case_id}"
    add_node(
        graph_case_id,
        f"Graph Case: {graph_case_id}",
        "InvestigationCase",
        {
            "status": payload.get("status"),
            "verdict": payload.get("verdict"),
            "probability": payload.get("fraud_probability"),
            "written_to_graph": payload.get("written_to_graph", False),
        }
    )
    if card_id:
        add_link(graph_case_id, card_id, "IC_ON_CARD")
    if cust_id:
        add_link(graph_case_id, cust_id, "IC_FOR_CUSTOMER")
    if flagged_txn_id:
        add_link(graph_case_id, flagged_txn_id, "IC_INVOLVES")

    return {
        "case_id": case_id,
        "nodes": nodes,
        "links": links,
        "counts": {"nodes": len(nodes), "links": len(links)},
    }


# ─── Static Frontend Mount ───────────────────────────────────────────────────

from pathlib import Path
from fastapi.staticfiles import StaticFiles

frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _reconstruct(payload: dict) -> Any:
    """Reconstruct an InvestigationCase from stored JSON."""
    from backend.models import InvestigationCase
    return InvestigationCase(**payload)

