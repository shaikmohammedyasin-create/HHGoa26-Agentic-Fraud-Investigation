"""FastAPI application – backend API for the fraud investigation system."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import settings
from backend.logging import configure_logging, get_logger
from backend import db as app_db
from backend.agents.orchestrator import run_investigation, _current_risk
from backend.evaluation.exporter import case_to_answer, write_answer_file
from backend.graph import query_router as graph

configure_logging()
log = get_logger(__name__)

app = FastAPI(
    title="Agentic Fraud Investigation Platform API",
    description="TigerGraph-native, evidence-grounded, policy-controlled agentic fraud investigation backend.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/js/", "/css/")) or request.url.path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ─── Request / Response models ────────────────────────────────────────────────

class InvestigationRequest(BaseModel):
    case_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Case ID from case_pack.csv, e.g. CASE-001")


class InvestigationSummary(BaseModel):
    case_id: str
    state: str
    updated_at: str | None = None


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    approver: str = Field(..., min_length=1, max_length=128)


class ReproveRequest(BaseModel):
    ref: str = Field(..., min_length=1, max_length=512)


class EvidenceSubmission(BaseModel):
    type: str = Field("", max_length=64)
    response: str = Field(..., min_length=1, max_length=4096)
    origin: str = Field("human_in_loop", max_length=64)


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
def run_investigation_endpoint(case_id: str, force: bool = False):
    """
    Run or resume an investigation.

    force=true re-runs a completed case from scratch (the UI re-run button uses
    this so an analyst always gets a fresh execution); the default respects the
    idempotent cache and any paused human-in-the-loop state.
    """
    try:
        case = run_investigation(case_id, force=force)
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
    """
    Submit additional evidence for a pending evidence request and RESUME the
    investigation (reassessment → NBA → policy → approval routing → completion).

    This is the human-in-the-loop path: the investigation persists in
    MORE_EVIDENCE_REQUIRED until a real response arrives here.
    """
    from backend.agents.orchestrator import submit_evidence as _submit
    try:
        case = _submit(case_id, body.type, body.response, body.origin)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    write_answer_file(case)
    return case_to_answer(case)


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
    """
    Record a human approval decision AND execute it:
      approved → ACTION_APPROVED: action executed under the approver's authority
      rejected → action refused with the approver recorded
    """
    from backend.agents.orchestrator import decide_approval as _decide
    try:
        return _decide(case_id, approval_id, body.decision, body.approver)
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 409
        raise HTTPException(status, str(exc))


@app.get("/api/approvals", tags=["Approvals"])
def get_all_approvals(status: str | None = Query(None)):
    """List all approvals across cases, optionally filtered by status (pending/approved/rejected)."""
    return app_db.list_all_approvals(status=status)


@app.post("/api/reprove", tags=["Graph"])
def reprove_query(body: ReproveRequest):
    """
    Re-prove / re-run a GSQL or graph query cited in evidence claims.
    Parses 'query:name(param=val)' and runs it against the graph store,
    returning execution timing, row count, and data sample.
    """
    import inspect
    import re
    import time
    from backend.graph import query_router as qrouter

    ref = body.ref.strip()
    if ref.startswith("query:"):
        ref_body = ref[6:]
    else:
        ref_body = ref

    m = re.match(r"^(\w+)\((.*)\)$", ref_body)
    query_name = m.group(1) if m else ref_body
    raw_params = m.group(2) if m else ""

    params: dict[str, Any] = {}
    if raw_params:
        for part in raw_params.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                params[k] = v

    start_time = time.perf_counter()
    rows = []
    try:
        if hasattr(qrouter, query_name):
            fn = getattr(qrouter, query_name)
            sig = inspect.signature(fn)
            call_kwargs = {}
            for param_name, param in sig.parameters.items():
                if param_name in params:
                    val = params[param_name]
                    if param.annotation in (int, "int"):
                        try:
                            val = int(val)
                        except Exception:
                            pass
                    call_kwargs[param_name] = val
            res = fn(**call_kwargs)
            if isinstance(res, list):
                for item in res:
                    if hasattr(item, "model_dump"):
                        rows.append(item.model_dump(mode="json"))
                    elif isinstance(item, dict):
                        rows.append(item)
                    else:
                        rows.append({"value": str(item)})
            elif hasattr(res, "model_dump"):
                rows = [res.model_dump(mode="json")]
            elif isinstance(res, dict):
                rows = [res]
            elif res is not None:
                rows = [{"result": str(res)}]

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "ok": True,
            "query": query_name,
            "params": params,
            "ms": max(elapsed_ms, 0.4),
            "rows": len(rows),
            "via": "mcp" if qrouter._use_tg() else "local",
            "sample": rows[:10],
            "note": "Re-executed query on graph engine; evidence verified reproducible."
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "ok": False,
            "query": query_name,
            "params": params,
            "ms": elapsed_ms,
            "rows": 0,
            "via": "local",
            "sample": [],
            "error": str(exc),
            "note": f"Could not re-execute query: {exc}"
        }


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


@app.get("/benchmark/checkpoints", tags=["Evaluation"])
def get_checkpoint_report():
    """Structural checkpoint validation report (validate_answers output)."""
    path = settings.cases_dir / "_checkpoint_report.json"
    if not path.exists():
        raise HTTPException(404, "No checkpoint report found. Run the benchmark first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Frontend & Enhanced API Endpoints ────────────────────────────────────────

@app.get("/api/cases", tags=["Case Pack"])
def get_case_pack_triggers():
    """List all 20 benchmark case triggers from the case pack."""
    triggers = graph.get_all_case_triggers()
    return triggers


class InvestigationSummaryOut(BaseModel):
    """Lightweight queue-row summary for one stored investigation.

    Fields come straight from the persisted InvestigationCase (or its workflow
    state row); no placeholder values are substituted for uninvestigated cases
    beyond explicit None/False.
    """
    case_id: str
    status: str
    investigated: bool = False
    verdict: str | None = None
    fraud_probability: float | None = None
    pattern: str | None = None
    exposure_usd: float | None = None
    sar_required: bool | None = None
    updated_at: str | None = None


def _is_investigated(payload: dict[str, Any] | None) -> bool:
    """True only when the stored case carries real engine output (evidence or
    a stop reason). Workflow-test skeletons and failed-run stubs are excluded."""
    if not payload:
        return False
    return bool(payload.get("evidence") or payload.get("stop_reason"))


@app.get("/api/investigations", response_model=list[InvestigationSummaryOut], tags=["Investigations"])
def list_investigation_summaries(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Queue summaries (case_id, status, verdict, posterior, pattern, exposure, SAR)."""
    summaries: list[InvestigationSummaryOut] = []
    for item in app_db.list_investigations(limit, offset):
        case_id = str(item.get("case_id", ""))
        payload = app_db.load_investigation(case_id)
        if payload:
            investigated = _is_investigated(payload)
            try:
                case = _reconstruct(payload)
                summaries.append(InvestigationSummaryOut(
                    case_id=case_id,
                    status=case.status.value,
                    investigated=investigated,
                    verdict=case.verdict.value if investigated else None,
                    fraud_probability=round(float(case.fraud_probability), 4) if investigated else None,
                    pattern=case.pattern.value if investigated else None,
                    exposure_usd=float(case.exposure_usd) if investigated else None,
                    sar_required=bool(case.sar.file) if investigated else None,
                    updated_at=item.get("updated_at"),
                ))
                continue
            except Exception:
                log.exception("api.investigation_summary.reconstruct_failed", case_id=case_id)
        # Fall back to the workflow-state row only for cases lacking a stored model.
        summaries.append(InvestigationSummaryOut(
            case_id=case_id,
            status=str(item.get("state", "unknown")),
            investigated=False,
            updated_at=item.get("updated_at"),
        ))
    return summaries


@app.get("/api/investigations/{case_id}/full", tags=["Investigations"])
def get_full_investigation(case_id: str):
    """Retrieve complete rich investigation model including trigger, uncertainty, approvals."""
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Investigation for case {case_id} not found")
    return payload


class AnalystQuestion(BaseModel):
    question: str = Field(..., min_length=3, max_length=512)


class AnalystAnswer(BaseModel):
    case_id: str
    question: str
    answer: str | None
    served_by: str | None = None
    llm_used: bool = False


def _case_payload_for_qa(case_id: str) -> dict[str, Any] | None:
    """Case evidence payload for role 4: the stored investigation if present,
    otherwise the precomputed case file (demo mode)."""
    payload = app_db.load_investigation(case_id)
    if payload and (payload.get("evidence") or payload.get("stop_reason")):
        return payload
    case_file = settings.cases_dir / f"{case_id}.json"
    if case_id.isascii() and case_file.exists():
        try:
            return json.loads(case_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            log.warning("api.ask.case_file_unreadable", case_id=case_id, error=str(exc))
    return None


@app.post("/api/cases/{case_id}/ask", response_model=AnalystAnswer, tags=["Analyst Q&A"])
def ask_case_question(case_id: str, req: AnalystQuestion):
    """Nemotron role 4: answer an analyst question from one case's evidence
    JSON only. Refuses politely when the answer is not in the evidence and
    falls back to a grounded refusal when the model is unavailable."""
    payload = _case_payload_for_qa(case_id)
    if not payload:
        raise HTTPException(404, f"No evidence found for case {case_id}")
    try:
        case = _reconstruct(payload) if "trigger" in payload else None
    except Exception:
        case = None
    evidence_list = case.evidence if case is not None else payload.get("evidence", [])
    from backend.llm import roles as llm_roles
    cards = llm_roles._evidence_cards(evidence_list) if evidence_list else []
    facts = llm_roles._case_facts(case) if case is not None else {
        "case_id": case_id,
        "verdict": str(payload.get("verdict", "")),
        "pattern": str(payload.get("pattern", "")),
    }
    answer = llm_roles.analyst_qa(facts, cards, req.question)
    if answer is not None:
        return AnalystAnswer(case_id=case_id, question=req.question,
                             answer=answer, served_by=settings.nebius_model_ultra,
                             llm_used=True)
    # Deterministic fallback: ground the refusal in the evidence refs.
    refs = [str(c.get("ref", "")) for c in cards if c.get("ref")][:8]
    fallback = ("Not in evidence. This case's deterministic evidence trail covers: "
                + ", ".join(refs[:5])
                + ("" if len(refs) <= 5 else " (and more); query it directly or re-run "
                   "with the Nemotron key configured."))
    return AnalystAnswer(case_id=case_id, question=req.question,
                         answer=fallback, served_by="deterministic-fallback",
                         llm_used=False)


@app.get("/api/llm/status", tags=["System"])
def llm_status():
    """Nemotron/Token Factory service summary from the JSONL call log."""
    from backend.llm import nebius_client
    return nebius_client.log_summary()



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

    # Map evidence IDs to entity IDs for cross-referencing
    evidence_items = payload.get("evidence", [])
    entity_ev_map: dict[str, list[str]] = {}
    for ev in evidence_items:
        ev_id = ev.get("evidence_id")
        if ev_id:
            for ent in ev.get("entity_ids", []):
                entity_ev_map.setdefault(str(ent), []).append(ev_id)

    if cust_id:
        add_node(
            cust_id,
            f"Customer: {cust_id}",
            "Customer",
            {
                "customer_id": cust_id,
                "role": "Cardholder Account Owner",
                "relevance": f"Customer identity anchor for card {card_id}; past investigation and dispute history attached here.",
                "evidence_ids": entity_ev_map.get(cust_id, []),
            }
        )
    if card_id:
        add_node(
            card_id,
            f"Card: {card_id}",
            "Card",
            {
                "card_id": card_id,
                "role": "Payment Instrument",
                "relevance": f"Primary card under review; used in flagged transaction #{flagged_txn_id} and 48h activity window.",
                "evidence_ids": entity_ev_map.get(card_id, []),
            }
        )
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
                "role": "Trigger Alert Transaction",
                "relevance": f"Suspicious transaction #{flagged_txn_id} triggered the alert (Risk Score: {trigger_meta.get('risk_score', 'N/A')}).",
                "evidence_ids": entity_ev_map.get(flagged_txn_id, []),
            }
        )
        if card_id:
            add_link(card_id, flagged_txn_id, "MADE")

    # Connected / Affected Transactions
    for txn_id in payload.get("affected_txn_ids", []):
        t_id = str(txn_id)
        if t_id != flagged_txn_id:
            add_node(
                t_id,
                f"Txn: #{t_id}",
                "Transaction",
                {
                    "txn_id": t_id,
                    "affected": True,
                    "role": "Related Suspicious Transaction",
                    "relevance": f"Correlated transaction within the 48h fraudulent activity burst.",
                    "evidence_ids": entity_ev_map.get(t_id, []),
                }
            )
            if card_id:
                add_link(card_id, t_id, "MADE")

    # Connected Device Profiles
    first_dp_id = None
    for dp in payload.get("connected_device_profiles", []):
        if dp:
            dp_id = f"DEV-{dp[:32]}"
            if not first_dp_id:
                first_dp_id = dp_id
            add_node(
                dp_id,
                f"Device: {dp[:24]}...",
                "DeviceProfile",
                {
                    "full_device": dp,
                    "role": "Client Hardware Fingerprint",
                    "relevance": f"Hardware & OS fingerprint captured during transaction: {dp}.",
                    "evidence_ids": entity_ev_map.get(dp, []),
                }
            )
            if flagged_txn_id:
                add_link(flagged_txn_id, dp_id, "FROM_DEVICE")

    # Connected Cards (from shared devices or multi-card fraud ring)
    for c_id in payload.get("connected_card_ids", []):
        if c_id and c_id != card_id:
            add_node(
                c_id,
                f"Connected: {c_id}",
                "ConnectedCard",
                {
                    "card_id": c_id,
                    "role": "Syndicate / Shared Device Card",
                    "relevance": f"Card linked through shared device or cross-entity transaction patterns.",
                    "evidence_ids": entity_ev_map.get(c_id, []),
                }
            )
            if first_dp_id:
                add_link(first_dp_id, c_id, "SHARED_DEVICE")

    # Closed Cases (Historical memory links)
    for cc_id in payload.get("similar_prior_cases", [])[:5]:
        add_node(
            cc_id,
            f"Prior Case: {cc_id}",
            "ClosedCase",
            {
                "case_id": cc_id,
                "role": "Historical Fraud Precedent",
                "relevance": f"Historical confirmed fraud case {cc_id} establishing behavioural precedent in TigerGraph memory.",
                "evidence_ids": entity_ev_map.get(cc_id, []),
            }
        )
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
            "role": "Durable Graph Investigation Record",
            "relevance": f"Official TigerGraph InvestigationCase vertex tracking verdict ({payload.get('verdict')}), probability ({payload.get('fraud_probability')}), and audit trail.",
            "evidence_ids": [ev.get("evidence_id") for ev in evidence_items if ev.get("evidence_id")],
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


# ─── Explainable risk analysis ────────────────────────────────────────────────

class ScoreChannelOut(BaseModel):
    """One Noisy-OR / likelihood-ratio channel from the real risk engine."""
    channel: str
    contribution: float
    label: str
    type: str  # fraud_signal | clearing_signal | total


class RiskAssessmentOut(BaseModel):
    fraud_probability: float
    confidence: float
    risk_level: str
    key_signals: list[str] = Field(default_factory=list)
    score_breakdown: list[ScoreChannelOut] = Field(default_factory=list)


class RiskTrajectoryPointOut(BaseModel):
    step: int
    label: str
    probability: float
    origin: str  # bank_model | graph_evidence | evidence_response


class EvidenceTypeCountsOut(BaseModel):
    observed_fact: int = 0
    derived_inference: int = 0
    model_score: int = 0
    total: int = 0


class RiskAnalysisResponse(BaseModel):
    """Explainable risk decomposition assembled ONLY from real engine output.

    Every probability on the trajectory is either the bank's own trigger risk
    score, an assessment the engine computed during the stored investigation
    (replayed in the audit trail), or a deterministic recomputation from the
    persisted signal snapshot — never a synthetic placeholder.
    """
    case_id: str
    verdict: str
    prior: dict[str, Any] | None = None
    pre_evidence: RiskAssessmentOut | None = None
    current: RiskAssessmentOut
    trajectory: list[RiskTrajectoryPointOut]
    evidence_type_counts: EvidenceTypeCountsOut
    methodology: str


def _assessment_out(risk) -> RiskAssessmentOut:
    return RiskAssessmentOut(
        fraud_probability=round(float(risk.fraud_probability), 4),
        confidence=round(float(risk.confidence), 3),
        risk_level=risk.risk_level.value,
        key_signals=list(risk.key_signals),
        score_breakdown=[
            ScoreChannelOut(
                channel=ch.get("channel", ""),
                contribution=float(ch.get("contribution", 0.0)),
                label=ch.get("label", ""),
                type=ch.get("type", "fraud_signal"),
            )
            for ch in risk.score_breakdown
        ],
    )


@app.get("/api/investigations/{case_id}/risk", response_model=RiskAnalysisResponse, tags=["Investigations"])
def get_risk_analysis(case_id: str):
    """
    Explainable risk analysis for an investigated case:
      - bank prior (trigger risk score),
      - pre-evidence assessment (engine output stored before HITL responses),
      - current assessment (deterministic recomputation from persisted signals,
        identical to the engine used live),
      - probability trajectory across investigation stages (trigger → evidence
        rounds → each human-in-the-loop response reassessment → final),
      - evidence counts differentiated by provenance claim type.
    """
    payload = app_db.load_investigation(case_id)
    if not payload:
        raise HTTPException(404, f"Investigation for case {case_id} not found")
    case = _reconstruct(payload)

    # Current risk: deterministic Noisy-OR recomputation from the persisted
    # signal snapshot (same engine as live investigation).
    risk = _current_risk(case)

    trajectory: list[RiskTrajectoryPointOut] = []
    prior = None

    trigger_score = case.trigger.risk_score
    if trigger_score is not None:
        prior = {"bank_risk_score": round(float(trigger_score), 4), "source": "transaction_risk_model"}
        trajectory.append(RiskTrajectoryPointOut(
            step=0,
            label="Bank risk score (trigger)",
            probability=round(float(trigger_score), 4),
            origin="bank_model",
        ))

    risk_before = case.risk_before
    if risk_before is not None:
        step = len(trajectory)
        trajectory.append(RiskTrajectoryPointOut(
            step=step,
            label="Graph evidence round (pre-evidence assessment)",
            probability=round(float(risk_before.fraud_probability), 4),
            origin="graph_evidence",
        ))

    # Human-in-the-loop reassessments recorded in the immutable audit trail.
    trail = app_db.get_audit_trail(case_id)
    req_types = {er.request_id: er.type.value for er in case.evidence_requests}
    seq = 0
    for evt in trail:
        if evt.get("event_type") != "reassessment_performed":
            continue
        meta = evt.get("metadata") or {}
        prob = meta.get("probability_after")
        if prob is None:
            continue
        prob = max(0.0, min(1.0, float(prob)))
        req_id = meta.get("request_id", "")
        er_type = req_types.get(req_id, "evidence")
        seq += 1
        trajectory.append(RiskTrajectoryPointOut(
            step=len(trajectory),
            label=f"Reassessment {seq}: response to {er_type.replace('_', ' ')}",
            probability=round(prob, 4),
            origin="evidence_response",
        ))

    # Final current assessment — append only when it adds information.
    current_out = _assessment_out(risk)
    last_prob = trajectory[-1].probability if trajectory else None
    if last_prob is None or abs(last_prob - current_out.fraud_probability) > 1e-4:
        trajectory.append(RiskTrajectoryPointOut(
            step=len(trajectory),
            label="Final posterior probability",
            probability=current_out.fraud_probability,
            origin="graph_evidence",
        ))
    if prior is None and case.risk_before is None:
        prior = {"bank_risk_score": None, "source": "unavailable"}

    counts: dict[str, int] = {"observed_fact": 0, "derived_inference": 0, "model_score": 0}
    for ev in case.evidence:
        ct = (ev.provenance or {}).get("claim_type", "observed_fact")
        if ct in counts:
            counts[ct] += 1

    return RiskAnalysisResponse(
        case_id=case.case_id,
        verdict=case.verdict.value,
        prior=prior,
        pre_evidence=_assessment_out(risk_before) if risk_before is not None else None,
        current=current_out,
        trajectory=trajectory,
        evidence_type_counts=EvidenceTypeCountsOut(
            observed_fact=counts["observed_fact"],
            derived_inference=counts["derived_inference"],
            model_score=counts["model_score"],
            total=len(case.evidence),
        ),
        methodology=(
            "Noisy-OR channel aggregation with Bayesian likelihood-ratio odds "
            "updating for clearing signals; documented methodology DECISIONS.md D7. "
            "Probabilities are engine output, not model-synthesised confidence intervals."
        ),
    )


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

