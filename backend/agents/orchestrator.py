"""
Investigation Orchestrator — adaptive investigation loop.

The agent runs in planner-driven rounds rather than a fixed query script:
each round the hybrid planner (backend.agents.planner) selects which graph
tools to run based on the evidence gaps still open, the risk engine scores the
evidence, and the evidence-gap engine (backend.agents.evidence_gap) decides
WHETHER additional evidence is worth requesting and WHICH request has the
highest expected decision impact.  All decision logic is deterministic; the
LLM (when configured) only drafts the natural-language plan rationale and the
final case narrative.

State machine:
TRIGGER → CASE_CREATED → INVESTIGATING → EVIDENCE_GATHERED → ASSESSING
→ (MORE_EVIDENCE_REQUIRED → EVIDENCE_REQUESTED → [EVIDENCE_RECEIVED → REASSESSING]
   | wait-for-human in human_in_loop mode)*
→ ACTION_RECOMMENDED → (APPROVAL_REQUIRED → ACTION_EXECUTING)?
→ ACTION_EXECUTED → COMPLETED

Evidence requests in `simulated` mode are synthetic, clearly labelled
(ER.origin="simulated"), and never presented as real customer contact.
In `human_in_loop` mode the investigation persists and stops in
MORE_EVIDENCE_REQUIRED; POST /investigations/{id}/evidence supplies the real
response and resumes the loop.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend import db as app_db
from backend.config import settings
from backend.agents import evidence_gap as egap
from backend.agents import planner
from backend.graph import query_router as graph
from backend.graphrag.context import build_context, to_llm_prompt
from backend.llm import client as llm
from backend.logging import get_logger
from backend.mcp import client as mcp_client
from backend.models import (
    Action, ActionRecommendation, ApprovalRequest, ApprovalRoute, AuditEvent,
    CaseStatus, Channel, EvidenceItem, EvidenceRequest, EvidenceRequestType,
    EvidenceSource, FraudPattern, HistoricalCase, InvestigationCase,
    InvestigationState, RiskAssessment, RiskLevel, SARRecord, TransactionRecord,
    TriggerRecord, TriggerType, UncertaintyItem, Verdict,
)
from backend.policies.engine import (
    PolicyInput, build_recommendations, can_auto_execute,
    should_file_sar, validate_action_permission,
)
from backend.risk.assessment import (
    EvidenceSignals, build_risk_assessment, should_request_more_evidence,
)
from backend.risk.independence import independent_evidence_count
from backend.risk.pattern_detector import detect_pattern

log = get_logger(__name__)


# ─── Evidence / audit helpers ──────────────────────────────────────────────────

def _ev(case_id: str, claim: str, source: EvidenceSource, ref: str,
        entity_ids: list[str] | None = None,
        severity: RiskLevel = RiskLevel.medium,
        confidence: float = 0.7,
        provenance: dict | None = None,
        step: int = 0,
        claim_type: str = "observed_fact") -> EvidenceItem:
    """
    Build an evidence item with full provenance.

    claim_type: observed_fact | derived_inference | model_score
    """
    prov = provenance or {}
    if "step" not in prov:
        prov["step"] = step
    if "claim_type" not in prov:
        prov["claim_type"] = claim_type
    if "query" not in prov and ref:
        raw = ref.split(":", 1)[-1].split("(")[0]
        prov["query"] = raw
    return EvidenceItem(
        case_id=case_id,
        claim=claim,
        source=source,
        ref=ref,
        entity_ids=entity_ids or [],
        severity=severity,
        confidence=confidence,
        provenance=prov,
    )


def _audit(case: InvestigationCase, event_type: str,
           state_from: str | None = None, state_to: str | None = None,
           metadata: dict | None = None) -> None:
    evt = AuditEvent(
        case_id=case.case_id,
        event_type=event_type,
        state_from=state_from,
        state_to=state_to,
        metadata=metadata or {},
    )
    app_db.append_audit_event(evt.model_dump())


def _transition(case: InvestigationCase, new_state: InvestigationState) -> None:
    old = case.state.value
    case.state = new_state
    case.step += 1
    case.updated_at = datetime.utcnow()
    _audit(case, "state_transition", state_from=old, state_to=new_state.value)
    _save(case)


def _save(case: InvestigationCase) -> None:
    app_db.save_investigation(case.case_id, case.state.value, case.model_dump(mode="json"))


# ─────────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────────

def run_investigation(case_id: str, force: bool = False) -> InvestigationCase:
    """
    Execute (or resume) an investigation.

    Resume semantics:
      - a case persisted in MORE_EVIDENCE_REQUIRED with a pending request is
        waiting for human evidence; it is returned as-is in human_in_loop mode
      - a case with a received-but-unprocessed request resumes at reassessment
      - a completed/failed case returns as-is unless force=True (benchmark)
    """
    t0 = time.time()
    log.info("investigation.start", case_id=case_id)

    existing = app_db.load_investigation(case_id)
    if existing and not force:
        case = InvestigationCase(**existing)
        if case.state in (InvestigationState.completed, InvestigationState.failed):
            log.info("investigation.already_complete", case_id=case_id, state=case.state)
            return case
        pending = [r for r in case.evidence_requests if r.status == "pending"]
        if pending and settings.evidence_request_mode == "human_in_loop":
            log.info("investigation.waiting_for_human_evidence",
                     case_id=case_id, request=pending[0].request_id)
            return case
        if pending:
            # Simulated mode: process the pending request now.
            return _resume_with_pending_request(case, t0)
        log.info("investigation.resume", case_id=case_id, state=case.state)
    else:
        if existing:
            log.info("investigation.force_rerun", case_id=case_id)
        case = _create_case(case_id)

    try:
        _run_adaptive_investigation(case, t0)
        return case
    except Exception as exc:
        log.exception("investigation.error", case_id=case_id, error=str(exc))
        _fail(case, str(exc))
        return case


def _run_adaptive_investigation(case: InvestigationCase, t0: float) -> None:
    """Phased, planner-driven investigation."""
    tool_calls = 0

    # ── STEP 0: Capability discovery (MCP) ────────────────────────────────────
    case.graph_backend = settings.graph_backend
    if settings.mcp_url:
        try:
            mcp_health = mcp_client.get_mcp().health()
            case.mcp_status = "ok" if mcp_health.get("status") == "healthy" else "unavailable"
        except Exception as exc:
            case.mcp_status = "unavailable"
            log.warning("mcp.unavailable", error=str(exc))
        _audit(case, "capability_check", metadata={
            "graph_backend": case.graph_backend, "mcp_status": case.mcp_status,
        })
    else:
        case.mcp_status = "not_configured"

    # ── Planner round 0: subject + baseline ───────────────────────────────────
    _transition(case, InvestigationState.investigating)

    plan0 = planner.plan_initial_round({
        "flagged_txn_id": case.flagged_txn_id,
        "card_id": case.card_id,
        "flagged_ts": _trigger_ts_hint(case),
    })
    case.plan_trace.append({
        "round": 0, "gap": plan0.gap, "tools": plan0.tool_names,
        "rationale": "Identify subject transaction and card baselines.",
    })
    _save(case)

    ctx: dict[str, Any] = {}

    for step in sorted(plan0.steps, key=lambda s: s.priority):
        fn = graph  # all planner tools are query-router functions
        try:
            result = getattr(fn, step.tool)(*step.args, **step.kwargs)
        except Exception as exc:
            log.warning("investigation.tool_failed", tool=step.tool, error=str(exc))
            result = None
        tool_calls += 1
        ctx[step.tool] = result

    flagged_txn: TransactionRecord | None = ctx.get("get_transaction")
    if flagged_txn is None:
        log.error("investigation.txn_not_found", txn_id=case.flagged_txn_id)
        _fail(case, f"Transaction {case.flagged_txn_id} not found in graph")
        return

    try:
        case.graph_case_id = graph.write_investigation_case(case.model_dump(mode="json"))
        _audit(case, "case_created_in_graph", metadata={"graph_case_id": case.graph_case_id})
    except Exception as exc:
        log.warning("investigation.initial_graph_write_skipped", error=str(exc))

    # Trigger evidence
    evidence: list[EvidenceItem] = [
        _ev(
            case.case_id,
            (f"Trigger ({case.trigger.trigger_type.value}): {case.trigger.trigger_text}"),
            EvidenceSource.customer if case.trigger.trigger_type == TriggerType.customer_report
            else EvidenceSource.external,
            f"trigger:{case.trigger.trigger_type.value}",
            entity_ids=[case.customer_id, case.card_id, case.flagged_txn_id],
            severity=RiskLevel.high if case.trigger.trigger_type == TriggerType.customer_report else RiskLevel.medium,
            confidence=0.85 if case.trigger.trigger_type == TriggerType.customer_report else 0.7,
            claim_type="model_score" if case.trigger.trigger_type == TriggerType.risk_score else "observed_fact",
        )
    ]

    flagged_identity = ctx.get("get_transaction_identity")
    device_label: str | None = None
    if flagged_identity:
        try:
            device_label = graph.get_device_profile_label(case.flagged_txn_id)
            if device_label:
                case.connected_device_profiles.append(device_label)
        except Exception as exc:
            log.warning("investigation.device_label_failed", error=str(exc))

    card_history = ctx.get("get_card_transaction_history") or []
    amount_stats = ctx.get("get_card_amount_stats") or {}
    window_txns = ctx.get("get_card_window") or []

    if card_history:
        avg_amt = float(amount_stats.get("avg_amt") or 0) or (
            sum(t.amount for t in card_history) / len(card_history))
        evidence.append(_ev(
            case.case_id,
            f"{len(card_history)} previous transactions retrieved for card {case.card_id}. "
            f"Average amount: ${avg_amt:.2f}.",
            EvidenceSource.graph,
            f"query:card_transaction_history(card_id={case.card_id})",
            entity_ids=[case.card_id],
            confidence=0.95,
        ))
    else:
        avg_amt = 0.0

    # ── Planner round 1: adaptive follow-ups chosen by evidence gaps ──────────
    online_window = [t for t in window_txns if t.channel == Channel.online]
    known_regions = set()
    try:
        region_history = graph.get_card_region_history(case.card_id)
        known_regions = {str(r["addr1"]) for r in region_history if r.get("addr1")}
    except Exception:
        region_history = []
    txn_region = str(flagged_txn.addr1) if flagged_txn.addr1 else None
    new_region = txn_region is not None and txn_region not in known_regions

    sig = EvidenceSignals(
        trigger_risk_score=case.trigger.risk_score,
        trigger_type=case.trigger.trigger_type.value,
        txn_amount=flagged_txn.amount,
        avg_card_amount=avg_amt,
        new_device=(flagged_identity is not None and
                    str(getattr(flagged_identity, "device_status", "")) == "New"),
        proxy_used=(flagged_identity is not None and
                    flagged_identity.proxy not in (None, "", "NotFound", "nan")),
        new_region=new_region,
        mixed_channel=len({t.channel.value for t in window_txns}) > 1,
        match_flag_anomaly=_match_anomaly(flagged_identity),
    )

    plan1 = planner.plan_adaptive_round({
        "signals": sig,
        "card_id": case.card_id,
        "customer_id": case.customer_id,
        "flagged_txn_id": case.flagged_txn_id,
        "flagged_ts": flagged_txn.ts,
        "device_label": device_label,
        "txn_region": txn_region,
        "new_region": new_region,
        "online_window_count": len(online_window),
        "trigger_risk_score": case.trigger.risk_score,
        "round": 1,
        "closed_gaps": [],
    })
    case.plan_trace.append({
        "round": 1, "gap": plan1.gap, "tools": plan1.tool_names,
        "rationale": ("Adaptive round: tools selected by open evidence gaps "
                      "(new region, device sharing, velocity, prior memory)."),
    })
    _save(case)

    region_streak = False
    sharing_accounts: list[dict] = []
    device_cases: list[HistoricalCase] = []
    fraud_ring: dict[str, Any] | None = None
    tiny_seq: list[TransactionRecord] = []

    for pstep in sorted(plan1.steps, key=lambda s: s.priority):
        tool = pstep.tool
        try:
            result = getattr(graph, tool)(*pstep.args, **pstep.kwargs)
        except Exception as exc:
            log.warning("investigation.tool_failed", tool=tool, error=str(exc))
            result = None
        tool_calls += 1

        if tool == "get_cards_in_same_region_window" and result:
            region_window = result
        elif tool == "get_accounts_sharing_device" and result:
            sharing_accounts = result
        elif tool == "get_device_fraud_ring" and result:
            fraud_ring = result
        elif tool == "get_closed_cases_by_device" and result:
            device_cases = result
        elif tool == "get_tiny_transaction_sequence" and result:
            tiny_seq = result
        elif tool == "get_closed_cases_for_customer" and result is not None:
            ctx.setdefault("customer_cases", result)
        elif tool == "get_closed_cases_for_card" and result is not None:
            ctx.setdefault("card_cases", result)
        elif tool == "get_closed_cases_involving_txn" and result is not None:
            ctx.setdefault("txn_cases", result)

    # Region streak (travel signal)
    if new_region and txn_region:
        card_region_txns = [t for t in window_txns if str(t.addr1) == txn_region]
        if card_region_txns:
            dates = {t.ts.date() for t in card_region_txns}
            region_streak = len(dates) >= 2
    sig.region_streak = region_streak

    # Card testing
    card_testing = len(tiny_seq) >= 3
    sig.card_testing_sequence = card_testing
    sig.small_online_count = len(tiny_seq)
    sig.burst_online = len(online_window)

    # Shared device
    other_cards = [a.get("card_id") for a in sharing_accounts
                   if a.get("card_id") and a.get("card_id") != case.card_id]
    device_card_count = len(other_cards)
    sig.shared_device_count = device_card_count

    # Prior case memory (graph-native)
    customer_cases = ctx.get("customer_cases") or []
    card_cases = ctx.get("card_cases") or []
    txn_cases = ctx.get("txn_cases") or []
    seen_case_ids: set[str] = set()
    all_prior: list[HistoricalCase] = []
    for hc in customer_cases + card_cases + device_cases + txn_cases:
        if hc.case_id not in seen_case_ids:
            seen_case_ids.add(hc.case_id)
            all_prior.append(hc)

    fraud_prior = [h for h in all_prior if h.outcome == "confirmed_fraud"]
    cleared_prior = [h for h in all_prior if h.outcome == "cleared"]
    sig.prior_fraud_cases = len(fraud_prior)
    sig.prior_cleared_cases = len(cleared_prior)
    sig.device_linked_fraud = sum(
        1 for h in device_cases if h.outcome == "confirmed_fraud")
    sig.connected_card_fraud = sum(
        1 for h in all_prior
        if h.outcome == "confirmed_fraud" and h.card_id != case.card_id)
    case.similar_prior_cases = [h.case_id for h in all_prior[:10]]

    # Fraud-ring signal (graph algorithm result)
    if fraud_ring and fraud_ring.get("ring_size", 0) > 0:
        sig.fraud_ring_size = fraud_ring.get("ring_size", 0)
        sig.fraud_ring_fraud_cards = fraud_ring.get("n_fraud", 0)

    # Agent case memory: prior investigations by this agent on this entity
    try:
        own_prior = graph.get_investigation_cases_for_customer(case.customer_id)
        own_prior = [p for p in own_prior if p.get("case_id") != case.case_id]
        sig.agent_prior_investigations = len(own_prior)
        sig.agent_prior_fraud = sum(
            1 for p in own_prior if p.get("verdict") == "fraud")
    except Exception as exc:
        log.warning("investigation.own_prior_failed", error=str(exc))
        own_prior = []

    # ── Evidence items for round-1 findings ───────────────────────────────────
    if card_testing:
        amounts = [f"${t.amount:.2f}" for t in tiny_seq]
        evidence.append(_ev(
            case.case_id,
            f"Card-testing sequence detected: {len(tiny_seq)} online "
            f"transactions ({', '.join(amounts)}) within a 2-hour window before flagged transaction.",
            EvidenceSource.graph,
            f"query:tiny_transaction_sequence(card_id={case.card_id})",
            entity_ids=[t.txn_id for t in tiny_seq],
            severity=RiskLevel.critical,
            confidence=0.90,
        ))

    if new_region and txn_region:
        if region_streak:
            evidence.append(_ev(
                case.case_id,
                f"Multiple-day transaction pattern in region {txn_region} "
                f"– may indicate legitimate travel rather than card cloning.",
                EvidenceSource.graph,
                f"query:card_window(card_id={case.card_id})",
                entity_ids=[case.card_id],
                severity=RiskLevel.low,
                confidence=0.70,
            ))
        else:
            evidence.append(_ev(
                case.case_id,
                f"Transaction in billing region {txn_region} "
                f"(no prior history for this card in this region).",
                EvidenceSource.graph,
                f"query:card_region_history(card_id={case.card_id})",
                entity_ids=[case.card_id, flagged_txn.txn_id],
                severity=RiskLevel.high,
                confidence=0.85,
            ))

    if sig.burst_online >= 2:
        evidence.append(_ev(
            case.case_id,
            f"{sig.burst_online} online transactions on this card within 48h of the flagged transaction.",
            EvidenceSource.graph,
            f"query:card_window(card_id={case.card_id}, hours=48)",
            entity_ids=[t.txn_id for t in online_window[:10]],
            severity=RiskLevel.high if sig.burst_online >= 3 else RiskLevel.medium,
            confidence=0.85,
        ))

    if sig.new_device:
        evidence.append(_ev(
            case.case_id,
            f"Device marked 'New' for this account: "
            f"{device_label or 'unknown device profile'}.",
            EvidenceSource.graph,
            f"query:transaction_identity(txn_id={case.flagged_txn_id})",
            entity_ids=[case.flagged_txn_id],
            severity=RiskLevel.high,
            confidence=0.80,
        ))

    if sig.proxy_used:
        evidence.append(_ev(
            case.case_id,
            f"Proxy or anonymous connection used: {flagged_identity.proxy}.",
            EvidenceSource.graph,
            f"query:transaction_identity(txn_id={case.flagged_txn_id})",
            entity_ids=[case.flagged_txn_id],
            severity=RiskLevel.medium,
            confidence=0.75,
        ))

    if device_card_count > 0:
        evidence.append(_ev(
            case.case_id,
            f"Device profile shared across {device_card_count} other card(s): "
            f"{', '.join(other_cards[:5])}.",
            EvidenceSource.graph,
            f"query:accounts_sharing_device(device={device_label})",
            entity_ids=other_cards[:10],
            severity=RiskLevel.high if device_card_count > 2 else RiskLevel.medium,
            confidence=0.80,
        ))
        case.connected_card_ids.extend(
            [c for c in other_cards[:10] if c not in case.connected_card_ids])

    if fraud_ring and fraud_ring.get("n_fraud", 0) >= 2:
        evidence.append(_ev(
            case.case_id,
            (f"Fraud-ring analysis: device component contains "
             f"{fraud_ring['n_fraud']} confirmed-fraud card(s) "
             f"(ring size {fraud_ring['ring_size']})."),
            EvidenceSource.graph,
            f"query:device_fraud_ring(device={device_label})",
            entity_ids=fraud_ring.get("fraud_cards", [])[:10],
            severity=RiskLevel.critical,
            confidence=0.85,
            claim_type="derived_inference",
        ))

    if fraud_prior:
        evidence.append(_ev(
            case.case_id,
            f"{len(fraud_prior)} prior confirmed fraud case(s) found for customer "
            f"{case.customer_id} or card {case.card_id}: "
            f"{', '.join(h.case_id for h in fraud_prior[:5])}.",
            EvidenceSource.graph,
            f"query:closed_cases_for_customer(customer_id={case.customer_id})",
            entity_ids=[h.case_id for h in fraud_prior[:5]],
            severity=RiskLevel.high,
            confidence=0.95,
        ))

    if device_fraud_count := sig.device_linked_fraud:
        evidence.append(_ev(
            case.case_id,
            f"Device profile '{device_label}' appears in {device_fraud_count} "
            f"confirmed fraud case(s).",
            EvidenceSource.graph,
            f"query:closed_cases_by_device(device={device_label})",
            entity_ids=[h.case_id for h in device_cases
                        if h.outcome == "confirmed_fraud"][:5],
            severity=RiskLevel.critical,
            confidence=0.90,
        ))

    if cleared_prior and not fraud_prior:
        evidence.append(_ev(
            case.case_id,
            f"{len(cleared_prior)} prior case(s) for this customer were cleared as "
            f"legitimate (e.g., confirmed travel, confirmed purchase).",
            EvidenceSource.graph,
            f"query:closed_cases_for_customer(customer_id={case.customer_id})",
            entity_ids=[h.case_id for h in cleared_prior[:3]],
            severity=RiskLevel.low,
            confidence=0.90,
        ))

    if sig.agent_prior_fraud > 0:
        evidence.append(_ev(
            case.case_id,
            (f"Agent case memory: {sig.agent_prior_fraud} of "
             f"{sig.agent_prior_investigations} prior investigation(s) on this "
             f"customer ended in confirmed fraud."),
            EvidenceSource.document,
            "memory:investigation_cases_for_customer",
            entity_ids=[case.customer_id],
            severity=RiskLevel.medium,
            confidence=0.80,
            claim_type="derived_inference",
        ))

    case.evidence = evidence
    sig.evidence_count = len(evidence)
    sig.independent_evidence_count = independent_evidence_count(evidence)

    # ── STEP: Assessment + pattern ────────────────────────────────────────────
    _transition(case, InvestigationState.evidence_gathered)
    _transition(case, InvestigationState.assessing)
    risk = build_risk_assessment(sig)
    case.risk_before = risk
    case.fraud_probability = risk.fraud_probability
    case.risk_level = risk.risk_level
    case.uncertainty = risk.uncertainty_items

    pat_result = detect_pattern(sig, case.trigger.trigger_type.value)
    case.pattern = pat_result.pattern
    case.pattern_description = (
        pat_result.description if pat_result.pattern != FraudPattern.none else "")
    case.pattern_candidates = pat_result.candidates
    if pat_result.secondary is not None:
        case.pattern_secondary = pat_result.secondary.value

    # ── STEP: GraphRAG retrieval round (pattern + keyword) ────────────────────
    retrieval_query = " ".join(
        [case.trigger.trigger_text] + [s.replace(" ", "_") for s in risk.key_signals]
    )
    plan2 = planner.plan_retrieval_round(case, {
        "pattern": case.pattern,
        "retrieval_query": retrieval_query,
        "round": 2,
    })
    case.plan_trace.append({
        "round": 2, "gap": plan2.gap, "tools": plan2.tool_names,
        "rationale": "Historical similarity retrieval for pattern context.",
    })
    retrieved: list[HistoricalCase] = []
    for pstep in sorted(plan2.steps, key=lambda s: s.priority):
        try:
            result = getattr(graph, pstep.tool)(*pstep.args, **pstep.kwargs)
        except Exception as exc:
            log.warning("investigation.tool_failed", tool=pstep.tool, error=str(exc))
            result = []
        tool_calls += 1
        if result:
            retrieved += result
    for hc in retrieved:
        if hc.case_id not in seen_case_ids:
            seen_case_ids.add(hc.case_id)
            all_prior.append(hc)
            case.similar_prior_cases.append(hc.case_id)
    case.similar_prior_cases = case.similar_prior_cases[:15]

    if retrieved:
        evidence.append(_ev(
            case.case_id,
            f"{len(retrieved)} prior closed case(s) retrieved by pattern "
            f"({case.pattern.value}) and keyword match over analyst notes.",
            EvidenceSource.document,
            f"retrieval:pattern+keyword(pattern={case.pattern.value})",
            entity_ids=[h.case_id for h in retrieved[:10]],
            severity=RiskLevel.low,
            confidence=0.75,
        ))
        case.evidence = evidence
        sig.evidence_count = len(evidence)
        sig.independent_evidence_count = independent_evidence_count(evidence)

    # ── STEP: Uncertainty-driven evidence loop (information-value based) ──────
    rounds_used = 0
    while rounds_used < settings.max_investigation_rounds:
        if not should_request_more_evidence(
                risk, sig, evidence_requests_so_far=len(case.evidence_requests),
                max_requests=settings.max_evidence_requests):
            case.stop_reason = case.stop_reason or "stopping criteria met; no further evidence request is decision-relevant"
            break

        # Information-value selection: WHAT to request (or nothing).
        shared_origin = device_card_count > 1 or bool(sig.device_linked_fraud)
        selection = egap.select_evidence_request(
            sig, exposure_usd=flagged_txn.amount,
            card_testing=card_testing,
            shared_origin=shared_origin,
            connected_fraud_cards=sig.connected_card_fraud,
            undocumented=(case.pattern == FraudPattern.undocumented),
            min_info_value=settings.min_evidence_info_value,
        )
        if selection is None:
            case.stop_reason = (
                "no unrequested evidence would materially change the decision "
                f"(best information value below {settings.min_evidence_info_value:.2f}); "
                "investigation halted per information-value stopping criterion")
            _audit(case, "evidence_gap_exhausted", metadata={
                "probability": risk.fraud_probability,
            })
            break

        cand: egap.EvidenceCandidate = selection["candidate"]
        rounds_used += 1
        # Persist the current signal snapshot BEFORE the request so the
        # reassessment (and any later resume) continues from the real state.
        _store_state(case, sig, risk)
        _transition(case, InvestigationState.more_evidence_required)

        req = EvidenceRequest(
            case_id=case.case_id,
            type=cand.type,
            asked_after_step=case.step,
            rationale=(
                f"Selected by information value {selection['info_value']:.2f} "
                f"(highest of candidates evaluated). {selection['decision_relevance']}"),
            question=cand.question,
            status="pending",
            info_value=selection["info_value"],
            alternatives_considered=[
                {
                    "type": s["candidate"].type.value,
                    "info_value": s["info_value"],
                    "decision_relevance": s["decision_relevance"],
                }
                for s in _score_all_candidates(
                    sig, flagged_txn.amount, card_testing, shared_origin, sig.connected_card_fraud,
                    case.pattern == FraudPattern.undocumented)
                if s["candidate"].type != cand.type
            ],
            decision_relevance=selection["decision_relevance"],
            origin="simulated",
        )
        _transition(case, InvestigationState.evidence_requested)
        case.evidence_requests.append(req)
        _save(case)
        _audit(case, "evidence_request_selected", metadata={
            "request_id": req.request_id,
            "type": cand.type.value,
            "info_value": req.info_value,
            "alternatives": [a["type"] for a in req.alternatives_considered],
        })

        # ── Human-in-the-loop pause ───────────────────────────────────────────
        if settings.evidence_request_mode == "human_in_loop":
            # Persist and stop; POST /investigations/{id}/evidence resumes.
            case.latency_s = round(time.time() - t0, 2)
            _save(case)
            log.info("investigation.paused_for_human_evidence",
                     case_id=case.case_id, request_id=req.request_id)
            return

        # ── Simulated mode: fabricate a documented synthetic response ─────────
        response = egap.simulate_response(
            cand.type, sig, case.trigger.trigger_type.value)
        _process_evidence_response(case, req, response, synthetic=True, sig=sig)
        req.origin = "simulated"

        # Reload the updated signal/risk state for the next round.
        sig = _current_signals(case, sig)
        risk = _current_risk(case)
        prob = risk.fraud_probability
        if prob >= settings.fraud_prob_stop_high or prob <= settings.fraud_prob_stop_low:
            break

    # Recompute final assessment state
    risk = _current_risk(case)
    sig = _current_signals(case, sig)

    # ── STEP: NBA before/after ────────────────────────────────────────────────
    evidence_before = [ev for ev in case.evidence
                       if not any(r.request_id and ev.ref.endswith(r.request_id)
                                  for r in case.evidence_requests)]
    pol_input_initial = _policy_input(
        case, flagged_txn, risk_at=evidence_before, sig=sig,
        device_card_count=device_card_count, card_testing=card_testing,
        connected_fraud=sig.connected_card_fraud,
        best_info_value=_max_pending_info_value(case),
    )
    case.nba_initial = build_recommendations(pol_input_initial)

    shared_origin_final = device_card_count > 1 or bool(sig.device_linked_fraud)
    pol_input_final = PolicyInput(
        fraud_probability=risk.fraud_probability,
        exposure_usd=flagged_txn.amount,
        customer_denied=sig.customer_denied,
        customer_confirmed=sig.customer_confirmed,
        no_reply=sig.customer_no_reply,
        card_testing_detected=card_testing,
        shared_origin=shared_origin_final,
        disputed_recurring=False,
        uncertain_exposed=(0.15 < risk.fraud_probability < 0.85
                           and flagged_txn.amount > 500),
        undocumented_coordinated=case.pattern == FraudPattern.undocumented,
        connected_fraud_cards_count=sig.connected_card_fraud,
        evidence_count=len(case.evidence),
        evidence_ids=[ev.evidence_id for ev in case.evidence[:10]],
        assessment_confidence=risk.confidence,
        best_evidence_info_value=_max_pending_info_value(case),
    )
    final_actions = build_recommendations(pol_input_final)
    case.nba_final = final_actions

    initial_names = {a.action for a in case.nba_initial}
    final_names = {a.action for a in final_actions}
    added = final_names - initial_names
    removed = initial_names - final_names
    if added or removed:
        parts: list[str] = []
        if added:
            parts.append(f"Added: {', '.join(a.value for a in added)}")
        if removed:
            parts.append(f"Removed: {', '.join(a.value for a in removed)}")
        case.nba_what_changed = "; ".join(parts)
    else:
        case.nba_what_changed = "nothing"

    _transition(case, InvestigationState.action_recommended)

    # ── STEP: Verdict + exposure ──────────────────────────────────────────────
    prob = risk.fraud_probability
    if prob >= settings.fraud_prob_stop_high:
        case.verdict = Verdict.fraud
    elif prob <= settings.fraud_prob_stop_low:
        case.verdict = Verdict.legitimate
    else:
        case.verdict = Verdict.uncertain

    if case.verdict == Verdict.legitimate:
        case.affected_txn_ids = []
        case.first_suspicious_txn_id = ""
        all_affected_txns: list[TransactionRecord] = []
        case.exposure_usd = 0.0
    else:
        affected = {case.flagged_txn_id}
        for t in tiny_seq:
            affected.add(t.txn_id)
        if case.verdict == Verdict.fraud:
            for t in online_window:
                affected.add(t.txn_id)
        case.affected_txn_ids = list(affected)

        first_sus = min(
            [(t.ts, t.txn_id) for t in tiny_seq + online_window + [flagged_txn]],
            default=(None, "")
        )
        case.first_suspicious_txn_id = first_sus[1] if first_sus else case.flagged_txn_id

        all_affected_txns = [flagged_txn] + tiny_seq
        if case.verdict == Verdict.fraud:
            all_affected_txns += online_window
        case.exposure_usd = round(sum(t.amount for t in all_affected_txns), 2)

    if case.verdict == Verdict.fraud:
        case.status = CaseStatus.closed_fraud
    elif case.verdict == Verdict.legitimate:
        case.status = CaseStatus.closed_legitimate
    else:
        if sig.customer_no_reply or (prob > 0.5 and case.exposure_usd > 500):
            case.status = CaseStatus.escalated
        else:
            case.status = CaseStatus.open

    # ── STEP: SAR ─────────────────────────────────────────────────────────────
    sar_file, sar_reason = should_file_sar(
        final_actions, case.exposure_usd,
        shared_origin=shared_origin_final,
        verdict=case.verdict.value,
    )

    rag_ctx = build_context(
        case=case,
        flagged_txn=flagged_txn,
        flagged_identity=flagged_identity,
        card_history=card_history,
        region_history=region_history,
        device_history=(ctx.get("get_card_device_history") or []),
        prior_cases=all_prior[:5],
        detected_pattern=case.pattern.value,
    )

    summary_prompt = to_llm_prompt(rag_ctx, task="summarize")
    summary_text, tok_summary, llm_used = llm.generate_summary(summary_prompt)
    case.llm_used = llm_used
    if not llm_used:
        summary_text = _grounded_summary(case, flagged_txn, sig)
    else:
        if case.case_id not in summary_text or case.card_id not in summary_text:
            summary_text = f"Case {case.case_id} (Card {case.card_id}): {summary_text}"
    case.summary = summary_text
    case.tokens_used += tok_summary

    if sar_file:
        nar_prompt = to_llm_prompt(rag_ctx, task="sar_narrative")
        nar_text, tok_nar, nar_llm_used = llm.generate_sar_narrative(nar_prompt)
        if not nar_llm_used:
            nar_text = _grounded_sar_narrative(case, flagged_txn, all_affected_txns, device_label)
        case.tokens_used += tok_nar

        activity_dates: list[str] = []
        if all_affected_txns:
            dates = sorted(t.ts.date() for t in all_affected_txns)
            activity_dates = [str(dates[0]), str(dates[-1])]

        subjects = list({case.customer_id, case.card_id} | set(case.connected_card_ids[:5]))
        if device_label:
            subjects.append(device_label[:80])

        case.sar = SARRecord(
            file=True,
            reason=sar_reason,
            narrative=nar_text,
            subjects=subjects,
            total_amount_usd=case.exposure_usd,
            activity_dates=activity_dates,
        )
    else:
        case.sar = SARRecord(file=False, reason=sar_reason)

    # ── STEP: Stop reason ─────────────────────────────────────────────────────
    if not case.stop_reason or "stopping criteria" not in case.stop_reason:
        if prob >= settings.fraud_prob_stop_high:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≥ {settings.fraud_prob_stop_high} "
                f"with {sig.independent_evidence_count} independent evidence families.")
        elif prob <= settings.fraud_prob_stop_low:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≤ {settings.fraud_prob_stop_low}; "
                f"activity consistent with legitimate use.")
        elif sig.customer_confirmed or sig.step_up_passed:
            case.stop_reason = "Cardholder verification settled the question; case closed as legitimate."
        elif sig.customer_denied or sig.step_up_failed:
            case.stop_reason = "Verification confirmed fraud indicators; final actions applied."
        else:
            case.stop_reason = (
                f"Borderline probability {prob:.2f}; investigation halted per stopping criteria. "
                "Escalated for analyst review.")

    # ── STEP: Write the case into the graph (case memory) ─────────────────────
    try:
        case.graph_case_id = graph.write_investigation_case(case.model_dump(mode="json"))
        case.written_to_graph = True
        tool_calls += 1
        _audit(case, "case_written_to_graph", metadata={
            "graph_case_id": case.graph_case_id,
            "backend": case.graph_backend,
        })
    except Exception as exc:
        case.written_to_graph = False
        case.graph_case_id = ""
        log.error("investigation.graph_write_failed", case_id=case.case_id, error=str(exc))
        _audit(case, "graph_write_failed", metadata={"error": str(exc)})

    # ── STEP: Permission validation, approval routing, execution ──────────────
    _route_and_execute(case, final_actions)

    case.tool_calls = tool_calls
    case.latency_s = round(time.time() - t0, 2)
    _transition(case, InvestigationState.completed)
    log.info("investigation.complete", case_id=case.case_id,
             verdict=case.verdict.value, probability=case.fraud_probability,
             latency_s=case.latency_s)


# ─── Evidence-request processing (shared by simulated + human-in-loop) ────────

def _resume_with_pending_request(case: InvestigationCase, t0: float) -> InvestigationCase:
    """Resume an investigation paused at MORE_EVIDENCE_REQUIRED (simulated mode)."""
    pending = [r for r in case.evidence_requests if r.status == "pending"][0]
    sig = _current_signals(case, EvidenceSignals(
        trigger_risk_score=case.trigger.risk_score,
        trigger_type=case.trigger.trigger_type.value,
    ))
    response = egap.simulate_response(
        pending.type, sig, case.trigger.trigger_type.value)
    try:
        _process_evidence_response(case, pending, response, synthetic=True, sig=sig)
        pending.origin = "simulated"
        _finish_investigation(case)
        return case
    except Exception as exc:
        log.exception("investigation.error", case_id=case.case_id, error=str(exc))
        _fail(case, str(exc))
        return case


def submit_evidence(case_id: str, request_type: str, response: str,
                    origin: str = "human_in_loop") -> InvestigationCase:
    """
    Human-in-the-loop entry point: attach a real response to the pending
    evidence request and resume the investigation (reassessment → NBA → …).
    """
    case_payload = app_db.load_investigation(case_id)
    if case_payload is None:
        raise ValueError(f"Case {case_id} not found")
    case = InvestigationCase(**case_payload)
    pending = [r for r in case.evidence_requests if r.status == "pending"]
    if not pending:
        raise ValueError(f"No pending evidence request for case {case_id}")
    req = pending[0]
    if request_type and request_type != req.type.value:
        raise ValueError(
            f"Pending request is of type {req.type.value}, got {request_type}")

    _process_evidence_response(
        case, req, response, synthetic=False,
        sig=_current_signals(case, EvidenceSignals(
            trigger_risk_score=case.trigger.risk_score,
            trigger_type=case.trigger.trigger_type.value)))
    req.origin = origin
    _save(case)

    # Resume the loop (assessment → NBA → completion) without re-running rounds.
    _finish_investigation(case)
    return case


def _process_evidence_response(case: InvestigationCase, req: EvidenceRequest,
                               response: str, synthetic: bool,
                               sig: EvidenceSignals | None = None) -> None:
    """
    Attach a response to a pending request and update signals + evidence.

    `sig` is the caller's current live signal state; when omitted it is
    rebuilt from the persisted snapshot (resume path).
    """
    req.assumed_response = response
    req.status = "received"
    req.received_at = datetime.utcnow()
    _transition(case, InvestigationState.evidence_received)

    if sig is None:
        sig = _current_signals(case, EvidenceSignals(
            trigger_risk_score=case.trigger.risk_score,
            trigger_type=case.trigger.trigger_type.value,
        ))
    updated = egap.apply_response_to_signals(sig, req.type, response)

    # Evidence item for the response — flagged as simulated or human-supplied.
    cust_ev = _ev(
        case.case_id,
        (f"Customer response (simulated): {response}" if synthetic
         else f"Evidence response ({req.origin}): {response}"),
        EvidenceSource.customer,
        f"evidence_request:{req.request_id}",
        entity_ids=[case.customer_id],
        severity=RiskLevel.high if _response_supports_fraud(req.type, response) else RiskLevel.low,
        confidence=0.80,
    )
    # Keep pre-request evidence for the initial NBA snapshot.
    if not any(ev.ref.endswith(req.request_id) for ev in case.evidence):
        case.evidence = [*case.evidence, cust_ev]

    updated.evidence_count = len(case.evidence)
    updated.independent_evidence_count = independent_evidence_count(case.evidence)

    # Reassess
    risk_before = _current_risk(case)
    prob_before = risk_before.fraud_probability if risk_before else case.fraud_probability
    _transition(case, InvestigationState.reassessing)
    risk = build_risk_assessment(updated)
    prob_after = risk.fraud_probability
    case.fraud_probability = risk.fraud_probability
    case.risk_level = risk.risk_level
    case.uncertainty = risk.uncertainty_items
    _store_state(case, updated, risk)

    resolution_impact = (
        f"{req.type.value} response changed fraud probability "
        f"{prob_before:.2f} → {prob_after:.2f}"
    )
    for item in case.uncertainty:
        if item.status == "open" and item.resolution_method in (
                "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH or VERIFY_WITH_CUSTOMER"):
            item.status = "resolved"
            item.resolved_by = req.request_id
            item.resolution_impact = resolution_impact
    _save(case)
    _audit(case, "reassessment_performed", metadata={
        "request_id": req.request_id,
        "probability_before": prob_before,
        "probability_after": prob_after,
    })


def _response_supports_fraud(request_type: EvidenceRequestType, response: str) -> bool:
    text = (response or "").lower()
    if request_type == EvidenceRequestType.customer_validation:
        return any(p in text for p in ("did not", "never made", "not make"))
    if request_type == EvidenceRequestType.step_up_auth:
        return "failed" in text or "not recognized" in text
    if request_type == EvidenceRequestType.analyst_info:
        return "confirm" in text and "fraud" in text
    if request_type == EvidenceRequestType.external_watchlist:
        return "hit" in text and "no " not in text[:4]
    return False


# ─── State passthrough helpers ─────────────────────────────────────────────────
# The signals/risk used during the loop are reconstructed from case state so a
# resumed investigation continues from the persisted state, not from scratch.

def _store_state(case: InvestigationCase, sig: EvidenceSignals,
                 risk: RiskAssessment) -> None:
    """Persist the current signal snapshot in the internal signal_store field."""
    case.signal_store = _signals_dict(sig)


def _signals_dict(sig: EvidenceSignals) -> dict[str, Any]:
    return {k: getattr(sig, k) for k in (
        "customer_denied", "customer_confirmed", "customer_no_reply",
        "step_up_failed", "step_up_passed", "analyst_confirms_shared_fraud",
        "analyst_clears_shared", "watchlist_hit", "watchlist_clear",
        "shared_device_count", "device_linked_fraud", "connected_card_fraud",
        "card_testing_sequence", "small_online_count", "burst_online",
        "new_device", "proxy_used", "new_region", "region_streak",
        "mixed_channel", "match_flag_anomaly", "fraud_ring_size",
        "fraud_ring_fraud_cards", "agent_prior_investigations",
        "agent_prior_fraud", "prior_fraud_cases", "prior_cleared_cases",
        "trigger_risk_score", "trigger_type", "txn_amount", "avg_card_amount",
        "evidence_count", "independent_evidence_count",
    )}


def _current_signals(case: InvestigationCase, base: EvidenceSignals) -> EvidenceSignals:
    """Rebuild EvidenceSignals from the persisted signal snapshot, if present."""
    snap: dict[str, Any] = dict(case.signal_store or {})
    for k, v in snap.items():
        if hasattr(base, k):
            setattr(base, k, v)
    return base


def _current_risk(case: InvestigationCase) -> RiskAssessment:
    """Reassess risk from the case's evidence + stored signal snapshot."""
    sig = EvidenceSignals(trigger_risk_score=case.trigger.risk_score,
                          trigger_type=case.trigger.trigger_type.value)
    sig = _current_signals(case, sig)
    sig.evidence_count = len(case.evidence)
    sig.independent_evidence_count = independent_evidence_count(case.evidence)
    return build_risk_assessment(sig)


def _current_signals_or_default(case: InvestigationCase) -> EvidenceSignals:
    return _current_signals(case, EvidenceSignals(
        trigger_risk_score=case.trigger.risk_score,
        trigger_type=case.trigger.trigger_type.value,
        evidence_count=len(case.evidence),
        independent_evidence_count=independent_evidence_count(case.evidence),
    ))


def _finish_investigation(case: InvestigationCase) -> None:
    """Complete a resumed case: verdict → SAR → memory → routing → completion."""
    sig = _current_signals_or_default(case)
    risk = _current_risk(case)
    t0 = time.time()
    tool_calls = 0

    try:
        # NBA before/after
        evidence_before = [ev for ev in case.evidence
                           if not any(r.request_id and ev.ref.endswith(r.request_id)
                                      for r in case.evidence_requests)]
        pol_initial = _policy_input(
            case, None, risk_at=evidence_before, sig=sig,
            device_card_count=sig.shared_device_count,
            card_testing=sig.card_testing_sequence,
            connected_fraud=sig.connected_card_fraud,
            best_info_value=_max_pending_info_value(case),
        )
        case.nba_initial = build_recommendations(pol_initial)

        pol_final = PolicyInput(
            fraud_probability=risk.fraud_probability,
            exposure_usd=case.exposure_usd or _exposure_hint(case),
            customer_denied=sig.customer_denied,
            customer_confirmed=sig.customer_confirmed,
            no_reply=sig.customer_no_reply,
            card_testing_detected=sig.card_testing_sequence,
            shared_origin=sig.shared_device_count > 1 or bool(sig.device_linked_fraud),
            disputed_recurring=False,
            uncertain_exposed=(0.15 < risk.fraud_probability < 0.85
                               and (case.exposure_usd or _exposure_hint(case)) > 500),
            undocumented_coordinated=case.pattern == FraudPattern.undocumented,
            connected_fraud_cards_count=sig.connected_card_fraud,
            evidence_count=len(case.evidence),
            evidence_ids=[ev.evidence_id for ev in case.evidence[:10]],
            assessment_confidence=risk.confidence,
            best_evidence_info_value=_max_pending_info_value(case),
        )
        final_actions = build_recommendations(pol_final)
        case.nba_final = final_actions
        initial_names = {a.action for a in case.nba_initial}
        final_names = {a.action for a in final_actions}
        added = final_names - initial_names
        removed = initial_names - final_names
        if added or removed:
            parts: list[str] = []
            if added:
                parts.append(f"Added: {', '.join(a.value for a in added)}")
            if removed:
                parts.append(f"Removed: {', '.join(a.value for a in removed)}")
            case.nba_what_changed = "; ".join(parts)
        else:
            case.nba_what_changed = "nothing"

        _transition(case, InvestigationState.action_recommended)

        prob = risk.fraud_probability
        if prob >= settings.fraud_prob_stop_high:
            case.verdict = Verdict.fraud
        elif prob <= settings.fraud_prob_stop_low:
            case.verdict = Verdict.legitimate
        else:
            case.verdict = Verdict.uncertain

        # Exposure is already computed in the first pass for resumed cases;
        # recompute when verdict changed to legitimate.
        if case.verdict == Verdict.legitimate:
            case.affected_txn_ids = []
            case.exposure_usd = 0.0

        if case.verdict == Verdict.fraud:
            case.status = CaseStatus.closed_fraud
        elif case.verdict == Verdict.legitimate:
            case.status = CaseStatus.closed_legitimate
        else:
            case.status = (CaseStatus.escalated
                           if sig.customer_no_reply or prob > 0.5
                           else CaseStatus.open)

        sar_file, sar_reason = should_file_sar(
            final_actions, case.exposure_usd,
            shared_origin=sig.shared_device_count > 1 or bool(sig.device_linked_fraud),
            verdict=case.verdict.value,
        )
        if sar_file and not case.sar.file:
            case.sar = SARRecord(file=True, reason=sar_reason,
                                 narrative=_grounded_sar_narrative(
                                     case, None, [], None),
                                 subjects=list({case.customer_id, case.card_id}),
                                 total_amount_usd=case.exposure_usd)
            case.sar.narrative = _grounded_sar_narrative(case, None, [], None)
            case.sar.reason = sar_reason
        elif not sar_file:
            case.sar.file = False
            case.sar.reason = sar_reason

        if not case.summary:
            case.summary = _grounded_summary(case, None, sig)

        if prob >= settings.fraud_prob_stop_high:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≥ {settings.fraud_prob_stop_high} "
                f"with {sig.independent_evidence_count} independent evidence families.")
        elif prob <= settings.fraud_prob_stop_low:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≤ {settings.fraud_prob_stop_low}; "
                f"activity consistent with legitimate use.")
        else:
            case.stop_reason = (
                f"Borderline probability {prob:.2f} after evidence reassessment; "
                "escalated for analyst review.")

        try:
            case.graph_case_id = graph.write_investigation_case(case.model_dump(mode="json"))
            case.written_to_graph = True
            tool_calls += 1
            _audit(case, "case_written_to_graph", metadata={
                "graph_case_id": case.graph_case_id, "backend": case.graph_backend})
        except Exception as exc:
            case.written_to_graph = False
            log.error("investigation.graph_write_failed", case_id=case.case_id, error=str(exc))
            _audit(case, "graph_write_failed", metadata={"error": str(exc)})

        _route_and_execute(case, final_actions)

        case.tool_calls += tool_calls
        case.latency_s = round(case.latency_s + (time.time() - t0), 2)
        _transition(case, InvestigationState.completed)
        log.info("investigation.resumed_complete", case_id=case.case_id,
                 verdict=case.verdict.value, probability=case.fraud_probability)
    except Exception as exc:
        log.exception("investigation.error", case_id=case.case_id, error=str(exc))
        _fail(case, str(exc))


# ─── Policy input / helpers ────────────────────────────────────────────────────

def _exposure_hint(case: InvestigationCase) -> float:
    return float(case.trigger.risk_score or 0) * 1000 or 100.0


def _max_pending_info_value(case: InvestigationCase) -> float:
    vals = [r.info_value for r in case.evidence_requests]
    return max(vals) if vals else 0.0


def _score_all_candidates(sig, exposure_usd, card_testing, shared_origin,
                          connected_fraud, undocumented) -> list[dict]:
    return egap.evaluate_candidates(
        sig, exposure_usd, card_testing, shared_origin,
        connected_fraud, undocumented)


def _policy_input(case: InvestigationCase, flagged_txn: TransactionRecord | None,
                  risk_at: Any, sig: EvidenceSignals, device_card_count: int,
                  card_testing: bool, connected_fraud: int,
                  best_info_value: float = 0.0) -> PolicyInput:
    """Build the initial (pre-additional-evidence) policy input."""
    # The "before" assessment uses only the evidence that existed before the
    # additional-evidence items arrived.
    ev_list = risk_at if isinstance(risk_at, list) else case.evidence
    if hasattr(risk_at, "fraud_probability"):
        prob = risk_at.fraud_probability
        conf = risk_at.confidence
    else:
        # Estimate probability restricted to pre-request evidence by rebuilding
        # signals without customer responses.
        sig_pre = _current_signals_or_default(case)
        sig_pre.customer_denied = False
        sig_pre.customer_confirmed = False
        sig_pre.customer_no_reply = False
        sig_pre.step_up_failed = False
        sig_pre.step_up_passed = False
        sig_pre.evidence_count = len(ev_list)
        from backend.risk.assessment import compute_fraud_probability, compute_confidence
        prob, _ = compute_fraud_probability(sig_pre)
        conf = compute_confidence(sig_pre, prob)
    exposure = flagged_txn.amount if flagged_txn is not None else _exposure_hint(case)
    return PolicyInput(
        fraud_probability=prob,
        exposure_usd=exposure,
        customer_denied=False,
        customer_confirmed=False,
        no_reply=False,
        card_testing_detected=card_testing,
        shared_origin=(device_card_count > 1 or bool(sig.device_linked_fraud)),
        disputed_recurring=False,
        uncertain_exposed=(0.15 < prob < 0.85 and exposure > 500),
        undocumented_coordinated=case.pattern == FraudPattern.undocumented,
        connected_fraud_cards_count=connected_fraud,
        evidence_count=len(ev_list),
        evidence_ids=[ev.evidence_id for ev in ev_list[:10] if hasattr(ev, "evidence_id")],
        assessment_confidence=conf,
        best_evidence_info_value=best_info_value,
    )


def _trigger_ts_hint(case: InvestigationCase) -> datetime:
    """The trigger time is a reasonable initial window centre."""
    return case.trigger.opened_at


def _match_anomaly(identity) -> bool:
    if identity is None:
        return False
    match_status = str(getattr(identity, "match_status", "") or "")
    return "0" in match_status or "mismatch" in match_status.lower()


# ─── Action routing and execution ──────────────────────────────────────────────

def _route_and_execute(case: InvestigationCase, actions: list[ActionRecommendation]) -> None:
    """
    Deterministic gate between recommendation and execution.

    Every action is permission-checked against the policy routing table.
    Only ``auto`` actions are executed by the agent; L1/L2 actions are recorded
    as pending ApprovalRequests and wait for a human decision.  No high-impact
    action bypasses its required approval.
    """
    from backend.models import ActionResult

    needs_human = False
    for rec in actions:
        ok, msg = validate_action_permission(rec.action, rec.route)
        if not ok:
            _audit(case, "permission_check_failed", metadata={
                "action": rec.action.value, "route": rec.route.value, "message": msg,
            })
            case.action_results.append(ActionResult(
                action=rec.action, status="failed", case_id=case.case_id, result=msg,
            ))
            continue

        if can_auto_execute(rec.action):
            case.action_results.append(ActionResult(
                action=rec.action, status="executed", case_id=case.case_id,
                result=f"Executed by agent under policy route=auto ({rec.reason})",
            ))
            _audit(case, "action_executed", metadata={"action": rec.action.value})
        else:
            needs_human = True
            apr = ApprovalRequest(
                case_id=case.case_id,
                action=rec.action,
                reason=rec.reason,
                evidence_ids=[ev.evidence_id for ev in case.evidence[:10]],
                policy_ref=rec.reason,
                required_route=rec.route,
            )
            case.approvals.append(apr)
            app_db.save_approval(apr.approval_id, case.case_id, apr.model_dump(mode="json"))
            case.action_results.append(ActionResult(
                action=rec.action, status="pending_approval", case_id=case.case_id,
                result=f"Awaiting {rec.route.value} approval",
                approval_ref=apr.approval_id,
            ))
            _audit(case, "approval_required", metadata={
                "action": rec.action.value, "route": rec.route.value,
                "approval_id": apr.approval_id,
            })

    if needs_human:
        _transition(case, InvestigationState.approval_required)
        # Non-auto actions stay pending; the agent does not execute them.
        _transition(case, InvestigationState.action_executing)
    else:
        _transition(case, InvestigationState.action_executed)


def decide_approval(case_id: str, approval_id: str, decision: str,
                    approver: str) -> dict[str, Any]:
    """
    Process a human approval decision.

    approve  → ACTION_APPROVED → the action is marked executed under the
               approver's authority, audit-logged.
    reject   → the action is marked failed/rejected with the approver recorded,
               audit-logged.

    The route validation is re-checked at decision time: an approval whose
    required route no longer matches policy is refused.
    """
    payload = app_db.load_approval(approval_id)
    if not payload or payload.get("case_id") != case_id:
        raise ValueError(f"Approval {approval_id} not found for case {case_id}")
    if payload.get("status") != "pending":
        raise ValueError(f"Approval {approval_id} already decided ({payload.get('status')})")

    action = Action(payload["action"])
    route = ApprovalRoute(payload["required_route"])
    ok, msg = validate_action_permission(action, route)
    if not ok:
        raise ValueError(f"Policy validation failed at approval time: {msg}")

    payload["status"] = "approved" if decision == "approved" else "rejected"
    payload["approver"] = approver
    decided_at = datetime.utcnow()
    payload["decided_at"] = decided_at.isoformat()
    app_db.save_approval(approval_id, case_id, payload)

    # Reflect the decision in the persisted case.
    case_payload = app_db.load_investigation(case_id)
    result_state: InvestigationState | None = None
    if case_payload:
        case = InvestigationCase(**case_payload)
        for apr in case.approvals:
            if apr.approval_id == approval_id:
                apr.status = payload["status"]
                apr.approver = approver
                apr.decided_at = decided_at
        from backend.models import ActionResult
        case.action_results.append(ActionResult(
            action=action,
            status="executed" if decision == "approved" else "failed",
            case_id=case_id,
            result=(f"Approved by {approver} under route={route.value}; action executed under human authority"
                    if decision == "approved"
                    else f"Rejected by {approver}; action not taken"),
            approval_ref=approval_id,
        ))
        _audit(case, "approval_granted" if decision == "approved" else "approval_rejected",
               metadata={"approval_id": approval_id, "action": action.value,
                         "approver": approver, "route": route.value})
        if decision == "approved":
            _audit(case, "action_executed", metadata={
                "action": action.value, "authority": f"human:{approver}"})
        if any(a.status == "pending" for a in case.approvals):
            result_state = None  # other approvals still pending
        else:
            result_state = InvestigationState.action_executed
        if result_state:
            case.state = result_state
        _save(case)

    return payload


# ─── Deterministic text fallbacks (used only when no LLM provider is set) ──────

def _grounded_summary(case: InvestigationCase, txn: TransactionRecord | None,
                      sig: EvidenceSignals) -> str:
    """Case-grounded summary. Deterministic — not LLM output."""
    txn_bit = ""
    if txn is not None:
        txn_bit = (f" around transaction {txn.txn_id} "
                   f"(${txn.amount:.2f}, {txn.channel.value})")
    bits = [
        f"Case {case.case_id} investigated {case.pattern.value} activity on card "
        f"{case.card_id} (customer {case.customer_id}){txn_bit}.",
        f"Assessed fraud probability {case.fraud_probability:.2f} "
        f"({case.risk_level.value} risk) from {len(case.evidence)} evidence items "
        f"across {sig.independent_evidence_count} independent evidence families.",
    ]
    if case.risk_before and case.risk_before.key_signals:
        bits.append(f"Key signals: {'; '.join(case.risk_before.key_signals[:4])}.")
    if case.evidence_requests:
        er = case.evidence_requests[0]
        bits.append(f"Additional evidence requested ({er.type.value}, "
                    f"information value {er.info_value:.2f}); "
                    f"response: {er.assumed_response}")
    bits.append(
        f"Final actions: {', '.join(a.action.value for a in case.nba_final)}."
    )
    return " ".join(bits)


def _grounded_sar_narrative(case: InvestigationCase, txn: TransactionRecord | None,
                            affected: list[TransactionRecord],
                            device_label: str | None) -> str:
    """Deterministic SAR narrative built from case facts. Not LLM output."""
    if affected:
        dates = sorted(t.ts.date() for t in affected)
        total = sum(t.amount for t in affected)
    elif txn is not None:
        dates = [txn.ts.date()]
        total = txn.amount
    else:
        dates = [case.trigger.opened_at.date()]
        total = case.exposure_usd
    who = f"customer {case.customer_id} and card {case.card_id}"
    if case.connected_card_ids:
        who += f", connected cards {', '.join(case.connected_card_ids[:3])}"
    if device_label:
        who += f", device profile '{device_label}'"

    return (
        f"Between {dates[0]} and {dates[-1]}, {who} were involved in "
        f"{len(affected) or 1} transaction(s) assessed as {case.verdict.value} "
        f"({case.pattern.value} pattern) with total exposure ${total:.2f}. "
        + (f"The flagged transaction {txn.txn_id} of ${txn.amount:.2f} "
           f"({txn.channel.value}, product {txn.product_cd}) is inconsistent with "
           f"the cardholder's established history. " if txn is not None else "")
        + f"Evidence supporting this assessment comprises {len(case.evidence)} items "
        f"including graph-retrieved transaction history, device records and prior case memory. "
        f"The activity is suspicious because it matches the {case.pattern.value} pattern "
        f"with assessed fraud probability {case.fraud_probability:.2f}. "
        f"Actions taken or pending: {', '.join(a.action.value for a in case.nba_final)}. "
        f"This report is filed under policy rule {(case.sar.reason or 'R2').split(':')[0]}."
    )


def _create_case(case_id: str) -> InvestigationCase:
    """Load case-pack trigger and create a new InvestigationCase."""
    row = graph.get_case_trigger(case_id)
    if row is None:
        raise ValueError(f"Case {case_id} not found in case_pack")

    trigger = TriggerRecord(
        case_id=str(row["case_id"]),
        opened_at=datetime.fromisoformat(str(row["opened_at"])),
        trigger_type=TriggerType(str(row["trigger_type"])),
        trigger_text=str(row["trigger_text"]),
        flagged_txn_id=str(row["flagged_txn_id"]),
        card_id=str(row["card_id"]),
        customer_id=str(row["customer_id"]),
        risk_score=float(row["risk_score"]) if row.get("risk_score") not in ("", None, "nan") else None,
    )
    case = InvestigationCase(
        case_id=case_id,
        trigger=trigger,
        customer_id=trigger.customer_id,
        card_id=trigger.card_id,
        flagged_txn_id=trigger.flagged_txn_id,
    )
    _save(case)
    _audit(case, "case_created", state_to=InvestigationState.triggered.value)
    log.info("investigation.case_created", case_id=case_id)
    return case


def _fail(case: InvestigationCase, reason: str) -> None:
    case.state = InvestigationState.failed
    case.stop_reason = reason
    _audit(case, "case_failed", metadata={"reason": reason})
    _save(case)
