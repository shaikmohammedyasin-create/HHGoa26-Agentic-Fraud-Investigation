"""
Investigation Orchestrator.

This is the core agent workflow.  It is a deterministic state machine with
explicit persisted states.  The LLM is called only for text generation at the
very end.

TRIGGER → CASE_CREATED → INVESTIGATING → EVIDENCE_GATHERED → ASSESSING
→ (MORE_EVIDENCE_REQUIRED → EVIDENCE_REQUESTED → EVIDENCE_RECEIVED → REASSESSING)?
→ ACTION_RECOMMENDED → (APPROVAL_REQUIRED → ACTION_APPROVED → ACTION_EXECUTING)?
→ ACTION_EXECUTED → COMPLETED
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend import db as app_db
from backend.config import settings
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
    get_route, should_file_sar, validate_action_permission,
)
from backend.risk.assessment import (
    EvidenceSignals, build_risk_assessment, should_request_more_evidence,
)
from backend.risk.pattern_detector import detect_pattern

log = get_logger(__name__)


# ─── Evidence request simulation ───────────────────────────────────────────────

def _simulate_customer_response(
    sig: EvidenceSignals, case: InvestigationCase
) -> str:
    """
    Deterministic simulation of customer validation response.

    Per README §5 and DECISIONS.md D8: responses are simulated and the
    assumption is documented in evidence_requests.

    Heuristics:
    - If strong fraud signals (card testing, device-linked fraud, new device + burst):
      simulate denial.
    - If region streak (plausible travel) or customer-confirmed patterns exist:
      simulate confirmation.
    - Otherwise: simulate denial for customer-report triggers, no-reply for risk-score triggers.
    """
    prob = sig.trigger_risk_score or 0.5

    if sig.card_testing_sequence or sig.device_linked_fraud > 0:
        return ("Customer states they did not make these purchases "
                "and still has the card in their possession.")

    if sig.region_streak:
        return ("Customer confirms they were traveling in this region "
                "during the dates in question.")

    if case.trigger.trigger_type == TriggerType.customer_report:
        return ("Customer reiterates they did not make this purchase "
                "and requests it be investigated.")

    # risk-score trigger with no strong signal: simulate no-reply after 24h window
    return "No response received within the 24-hour window."


# ─── Evidence builder helpers ──────────────────────────────────────────────────

def _ev(case_id: str, claim: str, source: EvidenceSource, ref: str,
        entity_ids: list[str] | None = None,
        severity: RiskLevel = RiskLevel.medium,
        confidence: float = 0.7) -> EvidenceItem:
    return EvidenceItem(
        case_id=case_id,
        claim=claim,
        source=source,
        ref=ref,
        entity_ids=entity_ids or [],
        severity=severity,
        confidence=confidence,
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


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_investigation(case_id: str, force: bool = False) -> InvestigationCase:
    """
    Execute a complete fraud investigation and return the finished case.

    Can be called on a new case_id (creates a new case) or on an existing one
    (resumes from the persisted state).

    ``force=True`` ignores a previously completed result and re-runs the case
    from scratch.  Used by the benchmark harness so a benchmark always reflects
    the current pipeline; the HTTP API keeps idempotent caching.
    """
    t0 = time.time()
    log.info("investigation.start", case_id=case_id)

    # ── Load or create case ──────────────────────────────────────────────────
    existing = app_db.load_investigation(case_id)
    if existing and not force:
        case = InvestigationCase(**existing)
        if case.state in (InvestigationState.completed, InvestigationState.failed):
            log.info("investigation.already_complete", case_id=case_id, state=case.state)
            return case
        log.info("investigation.resume", case_id=case_id, state=case.state)
    else:
        if existing:
            log.info("investigation.force_rerun", case_id=case_id)
        case = _create_case(case_id)

    tool_calls = 0

    def _graph(fn_name: str, *args, **kwargs):
        """One graph/retrieval tool call through the query router."""
        nonlocal tool_calls
        tool_calls += 1
        return getattr(graph, fn_name)(*args, **kwargs)

    # ── STEP 0: Capability discovery (MCP) ────────────────────────────────────
    # The TigerGraph MCP server is an optional tool surface.  If it is not
    # configured the investigation proceeds with the configured graph backend;
    # the missing capability is recorded, never papered over.
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

    try:
        # ── STEP 1: Identify subject transaction ─────────────────────────────
        _transition(case, InvestigationState.investigating)

        flagged_txn = _graph("get_transaction", case.flagged_txn_id)
        if flagged_txn is None:
            log.error("investigation.txn_not_found", txn_id=case.flagged_txn_id)
            _fail(case, f"Transaction {case.flagged_txn_id} not found in graph")
            return case

        log.info("investigation.txn_found", txn_id=flagged_txn.txn_id,
                 amount=flagged_txn.amount, channel=flagged_txn.channel.value)

        # ── STEP 2: Identity record ──────────────────────────────────────────
        flagged_identity = _graph("get_transaction_identity", case.flagged_txn_id)
        device_label: str | None = None
        if flagged_identity:
            device_label = _graph("get_device_profile_label", case.flagged_txn_id)
            if device_label:
                case.connected_device_profiles.append(device_label)

        # ── STEP 3: Card transaction history ─────────────────────────────────
        card_history = _graph("get_card_transaction_history", case.card_id, limit=50, before=flagged_txn.ts)
        region_history = _graph("get_card_region_history", case.card_id)
        device_history = _graph("get_card_device_history", case.card_id)
        amount_stats = _graph("get_card_amount_stats", case.card_id)
        product_history = _graph("get_card_product_history", case.card_id)

        # ── STEP 4: Window analysis ───────────────────────────────────────────
        window_txns = _graph("get_card_window", case.card_id, flagged_txn.ts, hours=48)
        tiny_seq = _graph("get_tiny_transaction_sequence", case.card_id, flagged_txn.ts)
        velocity = _graph("get_transaction_velocity", case.card_id, flagged_txn.ts, hours=24)

        # ── STEP 5: Device neighbor graph ─────────────────────────────────────
        sharing_accounts: list[dict] = []
        if device_label:
            sharing_accounts = _graph("get_accounts_sharing_device", device_label, limit=20)

        # ── STEP 6: Historical cases ──────────────────────────────────────────
        # Graph traversal retrieves the customer's, card's, device's and
        # transaction's prior cases directly from the graph.
        customer_cases = _graph("get_closed_cases_for_customer", case.customer_id)
        card_cases = _graph("get_closed_cases_for_card", case.card_id)
        device_cases: list[HistoricalCase] = []
        if device_label:
            device_cases = _graph("get_closed_cases_by_device", device_label)
        txn_cases = _graph("get_closed_cases_involving_txn", case.flagged_txn_id)

        # Merge and deduplicate
        seen_case_ids: set[str] = set()
        all_prior: list[HistoricalCase] = []
        for hc in customer_cases + card_cases + device_cases + txn_cases:
            if hc.case_id not in seen_case_ids:
                seen_case_ids.add(hc.case_id)
                all_prior.append(hc)

        # Cases previously written to the graph by this agent (case memory).
        own_prior = _graph("get_investigation_cases_for_customer", case.customer_id)

        fraud_prior = [h for h in all_prior if h.outcome == "confirmed_fraud"]
        cleared_prior = [h for h in all_prior if h.outcome == "cleared"]
        case.similar_prior_cases = [h.case_id for h in all_prior[:10]]

        # ── STEP 7: Build evidence signals ───────────────────────────────────
        _transition(case, InvestigationState.evidence_gathered)

        avg_amt = float(amount_stats.get("avg_amt") or 0)

        # Known-region set
        known_regions = {str(r["addr1"]) for r in region_history if r.get("addr1")}
        txn_region = str(flagged_txn.addr1) if flagged_txn.addr1 else None
        new_region = txn_region is not None and txn_region not in known_regions

        # Region streak: multi-day in-person purchases in the same new region (trip signal)
        region_streak = False
        if new_region and txn_region:
            region_window = _graph("get_cards_in_same_region_window", txn_region, flagged_txn.ts, days=4)
            # If the same card made purchases across multiple days in that region → trip
            card_region_txns = [t for t in window_txns if str(t.addr1) == txn_region]
            if card_region_txns:
                dates = {t.ts.date() for t in card_region_txns}
                region_streak = len(dates) >= 2

        # Burst of online txns in 48h window
        online_window = [t for t in window_txns if t.channel == Channel.online]
        burst_online = len(online_window)

        # New device signal
        new_device = (flagged_identity is not None and
                      str(getattr(flagged_identity, "device_status", "")) == "New")
        proxy_used = (flagged_identity is not None and
                      flagged_identity.proxy not in (None, "", "NotFound", "nan"))

        # Mixed channel (ATO signal): in-person + online around same time, different regions
        channels_in_window = {t.channel.value for t in window_txns}
        mixed_channel = len(channels_in_window) > 1

        # Match flag anomaly
        match_status = str(getattr(flagged_identity, "match_status", "") or "")
        match_flag_anomaly = "0" in match_status or "mismatch" in match_status.lower()

        # Card-testing sequence
        card_testing = len(tiny_seq) >= 3

        # Other cards on this device
        device_card_count = sum(
            1 for a in sharing_accounts if a.get("card_id") != case.card_id
        )

        # Fraud on connected cards
        connected_fraud_count = sum(
            1 for h in all_prior
            if h.outcome == "confirmed_fraud" and h.card_id != case.card_id
        )
        device_fraud_count = sum(
            1 for h in device_cases if h.outcome == "confirmed_fraud"
        )

        sig = EvidenceSignals(
            trigger_risk_score=case.trigger.risk_score,
            trigger_type=case.trigger.trigger_type.value,
            txn_amount=flagged_txn.amount,
            avg_card_amount=avg_amt,
            card_testing_sequence=card_testing,
            small_online_count=len(tiny_seq),
            burst_online=burst_online,
            new_device=new_device,
            proxy_used=proxy_used,
            new_region=new_region,
            region_streak=region_streak,
            mixed_channel=mixed_channel,
            match_flag_anomaly=match_flag_anomaly,
            prior_fraud_cases=len(fraud_prior),
            prior_cleared_cases=len(cleared_prior),
            device_linked_fraud=device_fraud_count,
            connected_card_fraud=connected_fraud_count,
            shared_device_count=device_card_count,
            evidence_count=0,        # updated below
            independent_evidence_count=0,
        )

        # ── STEP 8: Build evidence items ──────────────────────────────────────
        evidence: list[EvidenceItem] = []

        if card_history:
            evidence.append(_ev(
                case.case_id,
                f"{len(card_history)} previous transactions retrieved for card {case.card_id}. "
                f"Most recent: {card_history[0].ts.date()} ${card_history[0].amount:.2f} "
                f"({card_history[0].channel.value}). Average amount: ${avg_amt:.2f}.",
                EvidenceSource.graph,
                f"query:card_transaction_history(card_id={case.card_id})",
                entity_ids=[case.card_id],
                confidence=0.95,
            ))

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
            evidence.append(_ev(
                case.case_id,
                f"Transaction in billing region {txn_region} "
                f"(no prior history for this card in this region). "
                f"Prior regions: {', '.join(list(known_regions)[:5]) or 'none recorded'}.",
                EvidenceSource.graph,
                f"query:card_region_history(card_id={case.card_id})",
                entity_ids=[case.card_id, flagged_txn.txn_id],
                severity=RiskLevel.high,
                confidence=0.85,
            ))

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

        if burst_online >= 2:
            evidence.append(_ev(
                case.case_id,
                f"{burst_online} online transactions on this card within 48h of the flagged transaction.",
                EvidenceSource.graph,
                f"query:card_window(card_id={case.card_id}, hours=48)",
                entity_ids=[t.txn_id for t in online_window[:10]],
                severity=RiskLevel.high if burst_online >= 3 else RiskLevel.medium,
                confidence=0.85,
            ))

        if new_device:
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

        if proxy_used:
            evidence.append(_ev(
                case.case_id,
                f"Proxy or anonymous connection used: id_23={flagged_identity.proxy}.",
                EvidenceSource.graph,
                f"query:transaction_identity(txn_id={case.flagged_txn_id})",
                entity_ids=[case.flagged_txn_id],
                severity=RiskLevel.medium,
                confidence=0.75,
            ))

        if device_card_count > 0:
            other_cards = [a["card_id"] for a in sharing_accounts if a.get("card_id") != case.card_id]
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
            case.connected_card_ids.extend([c for c in other_cards[:10] if c not in case.connected_card_ids])

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

        if device_fraud_count > 0:
            evidence.append(_ev(
                case.case_id,
                f"Device profile '{device_label}' appears in {device_fraud_count} "
                f"confirmed fraud case(s).",
                EvidenceSource.graph,
                f"query:closed_cases_by_device(device={device_label})",
                entity_ids=[h.case_id for h in device_cases if h.outcome == "confirmed_fraud"][:5],
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

        if mixed_channel:
            evidence.append(_ev(
                case.case_id,
                f"Mixed-channel activity in 48h window: "
                f"{', '.join(channels_in_window)}.",
                EvidenceSource.graph,
                f"query:card_window(card_id={case.card_id})",
                entity_ids=[t.txn_id for t in window_txns[:5]],
                severity=RiskLevel.medium,
                confidence=0.70,
            ))

        if match_flag_anomaly:
            evidence.append(_ev(
                case.case_id,
                f"Match status anomaly on flagged transaction: {match_status}.",
                EvidenceSource.graph,
                f"query:transaction_identity(txn_id={case.flagged_txn_id})",
                entity_ids=[case.flagged_txn_id],
                severity=RiskLevel.medium,
                confidence=0.65,
            ))

        if case.trigger.trigger_type == TriggerType.customer_report:
            evidence.append(_ev(
                case.case_id,
                f"Customer {case.customer_id} reported: \"{case.trigger.trigger_text}\"",
                EvidenceSource.customer,
                "trigger:customer_report",
                entity_ids=[case.customer_id, case.card_id],
                severity=RiskLevel.high,
                confidence=0.85,
            ))

        case.evidence = evidence
        sig.evidence_count = len(evidence)
        sig.independent_evidence_count = len({ev.source for ev in evidence})

        # ── STEP 9: Risk assessment ───────────────────────────────────────────
        _transition(case, InvestigationState.assessing)
        risk = build_risk_assessment(sig)
        case.risk_before = risk
        case.fraud_probability = risk.fraud_probability
        case.risk_level = risk.risk_level
        case.uncertainty = risk.uncertainty_items

        # Pattern detection
        pat_result = detect_pattern(sig, case.trigger.trigger_type.value)
        case.pattern = pat_result.pattern
        case.pattern_description = (
            pat_result.description if pat_result.pattern != FraudPattern.none else ""
        )

        # ── STEP 9b: Retrieval (GraphRAG evidence layer) ──────────────────────
        # Prior cases are retrieved two ways and merged with the graph traversal
        # results above: by detected pattern, and by keyword match over the
        # analyst notes.  Retrieved cases become context for the reasoning step
        # and are cited in similar_prior_cases.
        retrieved: list[HistoricalCase] = []
        if case.pattern != FraudPattern.none:
            retrieved += _graph("get_closed_cases_by_pattern", case.pattern.value)
        retrieval_query = " ".join(
            [case.trigger.trigger_text] + [s.replace(" ", "_") for s in risk.key_signals]
        )
        retrieved += _graph("search_closed_cases_text", retrieval_query)
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
            sig.independent_evidence_count = len({ev.source for ev in evidence})

        # ── STEP 10: Decide if more evidence is needed ────────────────────────
        need_more = should_request_more_evidence(
            risk, sig, evidence_requests_so_far=len(case.evidence_requests),
            max_requests=settings.max_evidence_requests,
        )

        if need_more:
            _transition(case, InvestigationState.more_evidence_required)

            # Simulate request + response
            req = EvidenceRequest(
                case_id=case.case_id,
                type=EvidenceRequestType.customer_validation,
                asked_after_step=case.step,
                rationale="Fraud probability is borderline; customer input will resolve uncertainty.",
                question="Did you make this transaction?",
                status="pending",
            )
            _transition(case, InvestigationState.evidence_requested)
            case.evidence_requests.append(req)
            _save(case)

            # Simulate response
            assumed_response = _simulate_customer_response(sig, case)
            req.assumed_response = assumed_response
            req.status = "received"
            req.received_at = datetime.utcnow()
            _transition(case, InvestigationState.evidence_received)

            # Update signals from simulated response
            denied = ("did not" in assumed_response.lower()
                      or "never made" in assumed_response.lower()
                      or "reiterates they did not" in assumed_response.lower()
                      or "did not make" in assumed_response.lower())
            confirmed = ("confirms" in assumed_response.lower()
                         or "travel" in assumed_response.lower())
            no_reply = "no response" in assumed_response.lower()

            sig.customer_denied = denied
            sig.customer_confirmed = confirmed
            sig.customer_no_reply = no_reply

            # Add evidence item for customer response.  `evidence` must stay the
            # pre-request snapshot: the initial NBA is the recommendation that
            # existed before this evidence arrived.
            cust_ev = _ev(
                case.case_id,
                f"Customer response (simulated): {assumed_response}",
                EvidenceSource.customer,
                f"evidence_request:{req.request_id}",
                entity_ids=[case.customer_id],
                severity=RiskLevel.high if denied else RiskLevel.low,
                confidence=0.80,
            )
            case.evidence = [*evidence, cust_ev]

            # Reassess
            _transition(case, InvestigationState.reassessing)
            sig.evidence_count = len(case.evidence)
            sig.independent_evidence_count = len({ev.source for ev in case.evidence})
            risk = build_risk_assessment(sig)
            case.fraud_probability = risk.fraud_probability
            case.risk_level = risk.risk_level
            case.uncertainty = risk.uncertainty_items

        # ── STEP 11: Construct initial NBA (before additional evidence) ────────
        pol_input_initial = PolicyInput(
            fraud_probability=case.risk_before.fraud_probability if case.risk_before else risk.fraud_probability,
            exposure_usd=flagged_txn.amount,
            customer_denied=False,
            customer_confirmed=False,
            no_reply=False,
            card_testing_detected=card_testing,
            shared_origin=device_card_count > 1 or bool(device_fraud_count),
            disputed_recurring=False,
            uncertain_exposed=(0.15 < (case.risk_before.fraud_probability if case.risk_before else risk.fraud_probability) < 0.85
                               and flagged_txn.amount > 500),
            undocumented_coordinated=case.pattern == FraudPattern.undocumented,
            connected_fraud_cards_count=connected_fraud_count,
            evidence_count=len(evidence),
        )
        case.nba_initial = build_recommendations(pol_input_initial)

        # ── STEP 12: Final NBA (after additional evidence) ────────────────────
        pol_input_final = PolicyInput(
            fraud_probability=risk.fraud_probability,
            exposure_usd=flagged_txn.amount,
            customer_denied=sig.customer_denied,
            customer_confirmed=sig.customer_confirmed,
            no_reply=sig.customer_no_reply,
            card_testing_detected=card_testing,
            shared_origin=device_card_count > 1 or bool(device_fraud_count),
            disputed_recurring=False,
            uncertain_exposed=(0.15 < risk.fraud_probability < 0.85 and flagged_txn.amount > 500),
            undocumented_coordinated=case.pattern == FraudPattern.undocumented,
            connected_fraud_cards_count=connected_fraud_count,
            evidence_count=len(case.evidence),
        )
        final_actions = build_recommendations(pol_input_final)
        case.nba_final = final_actions

        # Compute what changed
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

        # ── STEP 13: Determine verdict and exposure ───────────────────────────
        prob = risk.fraud_probability
        if prob >= settings.fraud_prob_stop_high:
            case.verdict = Verdict.fraud
        elif prob <= settings.fraud_prob_stop_low:
            case.verdict = Verdict.legitimate
        else:
            case.verdict = Verdict.uncertain

        # Affected transactions: flagged + tiny sequence.  A legitimate verdict
        # has no fraud episode, so per the answer-format notes the affected
        # transaction list is empty and exposure is zero.
        if case.verdict == Verdict.legitimate:
            case.affected_txn_ids = []
            case.first_suspicious_txn_id = ""
            all_affected_txns: list[TransactionRecord] = []
            case.exposure_usd = 0.0
        else:
            affected = {case.flagged_txn_id}
            for t in tiny_seq:
                affected.add(t.txn_id)
            # Add burst window online txns if verdict is fraud
            if case.verdict == Verdict.fraud:
                for t in online_window:
                    affected.add(t.txn_id)
            case.affected_txn_ids = list(affected)

            first_sus = min(
                [(t.ts, t.txn_id) for t in tiny_seq + online_window + [flagged_txn]],
                default=(None, "")
            )
            case.first_suspicious_txn_id = first_sus[1] if first_sus else case.flagged_txn_id

            # Exposure = sum of affected amounts
            all_affected_txns = [flagged_txn] + tiny_seq
            if case.verdict == Verdict.fraud:
                all_affected_txns += online_window
            case.exposure_usd = round(sum(t.amount for t in all_affected_txns), 2)

        # Case status
        if case.verdict == Verdict.fraud:
            case.status = CaseStatus.closed_fraud
        elif case.verdict == Verdict.legitimate:
            case.status = CaseStatus.closed_legitimate
        else:
            if sig.customer_no_reply or (prob > 0.5 and case.exposure_usd > 500):
                case.status = CaseStatus.escalated
            else:
                case.status = CaseStatus.open

        # ── STEP 14: SAR ──────────────────────────────────────────────────────
        sar_file, sar_reason = should_file_sar(
            final_actions,
            case.exposure_usd,
            shared_origin=device_card_count > 1 or bool(device_fraud_count),
            verdict=case.verdict.value,
        )

        # Build context for LLM text generation
        rag_ctx = build_context(
            case=case,
            flagged_txn=flagged_txn,
            flagged_identity=flagged_identity,
            card_history=card_history,
            region_history=region_history,
            device_history=device_history,
            prior_cases=all_prior[:5],
            detected_pattern=case.pattern.value,
        )

        # ── STEP 15: Generate summary ─────────────────────────────────────────
        # When a real LLM provider is configured it writes the summary from the
        # GraphRAG context.  Otherwise a deterministic, case-grounded summary is
        # produced — never presented as model output (case.llm_used records which).
        summary_prompt = to_llm_prompt(rag_ctx, task="summarize")
        summary_text, tok_summary, llm_used = llm.generate_summary(summary_prompt)
        case.llm_used = llm_used
        if not llm_used:
            summary_text = _grounded_summary(case, flagged_txn, sig)
        case.summary = summary_text
        case.tokens_used += tok_summary

        # ── STEP 16: SAR narrative ────────────────────────────────────────────
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
            case.sar = SARRecord(
                file=False,
                reason=sar_reason,
            )

        # ── STEP 17: Stop reason ──────────────────────────────────────────────
        if prob >= settings.fraud_prob_stop_high:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≥ {settings.fraud_prob_stop_high} "
                f"with {sig.independent_evidence_count} independent evidence sources."
            )
        elif prob <= settings.fraud_prob_stop_low:
            case.stop_reason = (
                f"Fraud probability {prob:.2f} ≤ {settings.fraud_prob_stop_low}; "
                f"activity consistent with legitimate use."
            )
        elif sig.customer_confirmed:
            case.stop_reason = "Customer confirmed the transaction; case closed as legitimate."
        elif sig.customer_denied:
            case.stop_reason = "Customer denial settled the question; final actions applied."
        else:
            case.stop_reason = (
                f"Borderline probability {prob:.2f}; investigation halted per stopping criteria. "
                "Escalated for analyst review."
            )

        # ── STEP 18: Write the case into the graph (case memory) ───────────────
        # Persisted as an InvestigationCase vertex (TigerGraph) or into the
        # graph store's investigation_cases tables (local).  A later
        # investigation retrieves it the same way it retrieves closed_cases.
        try:
            case.graph_case_id = graph.write_investigation_case(case.model_dump(mode="json"))
            case.written_to_graph = True
            tool_calls += 1
            _audit(case, "case_written_to_graph", metadata={
                "graph_case_id": case.graph_case_id,
                "backend": case.graph_backend,
            })
        except Exception as exc:
            # Missing case memory degrades future investigations, but the
            # investigation itself is already complete and must not be lost.
            case.written_to_graph = False
            case.graph_case_id = ""
            log.error("investigation.graph_write_failed", case_id=case_id, error=str(exc))
            _audit(case, "graph_write_failed", metadata={"error": str(exc)})

        # ── STEP 19: Permission validation, approval routing, execution ───────
        _route_and_execute(case, final_actions)

        # ── STEP 20: Complete ─────────────────────────────────────────────────
        case.tool_calls = tool_calls
        case.latency_s = round(time.time() - t0, 2)
        _transition(case, InvestigationState.completed)
        log.info("investigation.complete", case_id=case_id,
                 verdict=case.verdict.value, probability=case.fraud_probability,
                 latency_s=case.latency_s)
        return case

    except Exception as exc:
        log.exception("investigation.error", case_id=case_id, error=str(exc))
        _fail(case, str(exc))
        return case


# ─── Action routing and execution ─────────────────────────────────────────────


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


# ─── Deterministic text fallbacks (used only when no LLM provider is set) ─────


def _grounded_summary(case: InvestigationCase, txn: TransactionRecord,
                      sig: EvidenceSignals) -> str:
    """Case-grounded summary. Deterministic — not LLM output."""
    bits = [
        f"Case {case.case_id} investigated {case.pattern.value} activity on card "
        f"{case.card_id} (customer {case.customer_id}) "
        f"around transaction {txn.txn_id} (${txn.amount:.2f}, {txn.channel.value}).",
        f"Assessed fraud probability {case.fraud_probability:.2f} "
        f"({case.risk_level.value} risk) from {len(case.evidence)} evidence items "
        f"across {sig.independent_evidence_count} independent sources.",
    ]
    if case.risk_before and case.risk_before.key_signals:
        bits.append(f"Key signals: {'; '.join(case.risk_before.key_signals[:4])}.")
    if case.evidence_requests:
        er = case.evidence_requests[0]
        bits.append(f"Additional evidence requested ({er.type.value}); "
                    f"assumed response: {er.assumed_response}")
    bits.append(
        f"Final actions: {', '.join(a.action.value for a in case.nba_final)}."
    )
    return " ".join(bits)


def _grounded_sar_narrative(case: InvestigationCase, txn: TransactionRecord,
                            affected: list[TransactionRecord],
                            device_label: str | None) -> str:
    """Deterministic SAR narrative built from case facts. Not LLM output."""
    dates = sorted(t.ts.date() for t in affected) if affected else [txn.ts.date()]
    total = sum(t.amount for t in affected) if affected else txn.amount
    who = f"customer {case.customer_id} and card {case.card_id}"
    if case.connected_card_ids:
        who += f", connected cards {', '.join(case.connected_card_ids[:3])}"
    if device_label:
        who += f", device profile '{device_label}'"

    return (
        f"Between {dates[0]} and {dates[-1]}, {who} were involved in "
        f"{len(affected) or 1} transaction(s) assessed as {case.verdict.value} "
        f"({case.pattern.value} pattern) with total exposure ${total:.2f}. "
        f"The flagged transaction {txn.txn_id} of ${txn.amount:.2f} "
        f"({txn.channel.value}, product {txn.product_cd}) is inconsistent with "
        f"the cardholder's established history. "
        f"Evidence supporting this assessment comprises {len(case.evidence)} items "
        f"including graph-retrieved transaction history, device records and prior case memory. "
        f"The activity is suspicious because it matches the {case.pattern.value} pattern "
        f"with assessed fraud probability {case.fraud_probability:.2f}. "
        f"Actions taken or pending: {', '.join(a.action.value for a in case.nba_final)}. "
        f"This report is filed under policy rule {case.sar.reason.split(':')[0]}."
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
