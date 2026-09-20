"""
Policy engine.

Implements the Fraud Policy (R1-R10) from the README exactly.
Rules take structured evidence signals and return recommended actions with routes.
The LLM recommendation is passed to validate_recommendation() for gate checking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.models import Action, ApprovalRoute, ActionRecommendation, RiskLevel

# ─── Approval routing table (from policy §2) ──────────────────────────────────

_AUTO_ACTIONS = {
    Action.ALLOW_TRANSACTION,
    Action.MONITOR_CARD,
    Action.MONITOR_CONNECTED_CARDS,
    Action.WARN_CUSTOMER,
    Action.VERIFY_WITH_CUSTOMER,
    Action.STEP_UP_AUTH,
    Action.GENERATE_REPORT,
    Action.CREATE_CASE,
    Action.ESCALATE_TO_ANALYST,
    Action.CLOSE_NO_FRAUD,
}


def get_route(action: Action, exposure_usd: float = 0.0) -> ApprovalRoute:
    """Policy §2 – approval routing."""
    if action in _AUTO_ACTIONS:
        return ApprovalRoute.auto
    if action == Action.DECLINE_TRANSACTION:
        return ApprovalRoute.L1
    if action == Action.BLOCK_CARD:
        return ApprovalRoute.L1 if exposure_usd <= 2500.0 else ApprovalRoute.L2
    if action == Action.BLOCK_ALL_CARDS:
        return ApprovalRoute.L2
    if action == Action.FILE_REPORT:
        return ApprovalRoute.L2
    return ApprovalRoute.auto  # default – safe fallback


# ─── Signal record passed into every rule ────────────────────────────────────

@dataclass
class PolicyInput:
    fraud_probability: float
    exposure_usd: float
    customer_denied: bool                 # customer confirmed they did not make it
    customer_confirmed: bool              # customer confirmed they made it
    no_reply: bool                        # no reply within 24 hours
    card_testing_detected: bool           # R5 sequence
    shared_origin: bool                   # R6 – shared device / region / email
    disputed_recurring: bool              # R7 – disputed but looks recurring
    uncertain_exposed: bool               # R8 – uncertain verdict + exposure > 500
    undocumented_coordinated: bool        # R9
    connected_fraud_cards_count: int = 0 # R10
    evidence_count: int = 0
    # D.5: evidence IDs available to link into recommendations
    evidence_ids: list[str] = None        # type: ignore[assignment]

    def __post_init__(self):
        if self.evidence_ids is None:
            self.evidence_ids = []


def build_recommendations(inp: PolicyInput) -> list[ActionRecommendation]:
    """
    Apply policy rules R1-R10 in priority order and return a ranked list.

    D.5: Each recommendation now carries:
    - evidence_ids   : evidence items that triggered this rule
    - alternatives_rejected : why competing actions were not selected
    - expected_impact: what this action accomplishes
    """
    actions: list[ActionRecommendation] = []
    ev_ids = inp.evidence_ids or []

    # R10 – never BLOCK_ALL_CARDS unless ≥2 cards confirmed fraudulent
    can_block_all = inp.connected_fraud_cards_count >= 2

    # ── R5 card testing ──────────────────────────────────────────────────────────
    if inp.card_testing_detected:
        if inp.exposure_usd > 100:
            actions.append(ActionRecommendation(
                action=Action.BLOCK_CARD,
                route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
                reason="R5: card-testing sequence detected, purchase over $100 already cleared",
                evidence_ids=ev_ids[:5],
                alternatives_rejected=[
                    "DECLINE_TRANSACTION: transaction already cleared, blocking prevents further abuse",
                    "MONITOR_CARD: insufficient — testing sequence requires immediate card suspension",
                ],
                expected_impact="Prevents further card-testing abuse and unauthorized purchases on this card",
            ))
        else:
            actions.append(ActionRecommendation(
                action=Action.DECLINE_TRANSACTION,
                route=ApprovalRoute.L1,
                reason="R5: card-testing sequence detected",
                evidence_ids=ev_ids[:5],
                alternatives_rejected=[
                    "BLOCK_CARD: exposure under $100; decline is proportionate",
                ],
                expected_impact="Stops the flagged transaction before further testing can proceed",
            ))
            actions.append(ActionRecommendation(
                action=Action.STEP_UP_AUTH,
                route=ApprovalRoute.auto,
                reason="R5: require confirmation before further activity",
                evidence_ids=ev_ids[:3],
                alternatives_rejected=[],
                expected_impact="Adds friction to deter further automated card-testing attempts",
            ))

    # ── R2 customer denied ──────────────────────────────────────────────────────────
    elif inp.customer_denied:
        actions.append(ActionRecommendation(
            action=Action.BLOCK_CARD,
            route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
            reason="R2: customer denied the transaction",
            evidence_ids=ev_ids[:5],
            alternatives_rejected=[
                "MONITOR_CARD: insufficient — cardholder confirmed fraud; card must be suspended immediately",
                "VERIFY_WITH_CUSTOMER: already done — cardholder has denied the transaction",
            ],
            expected_impact="Prevents further unauthorized charges on the compromised card",
        ))
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R2",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Creates an official investigation record for compliance and audit trail",
        ))
        if inp.exposure_usd > 1000 or inp.shared_origin:
            actions.append(ActionRecommendation(
                action=Action.FILE_REPORT,
                route=ApprovalRoute.L2,
                reason="R2: exposure > $1,000 or shared device/region",
                evidence_ids=ev_ids[:5],
                alternatives_rejected=[
                    "GENERATE_REPORT: internal report insufficient — SAR threshold reached",
                ],
                expected_impact="Fulfils regulatory obligation to file SAR for confirmed fraud above threshold",
            ))
        if inp.shared_origin:
            actions.append(ActionRecommendation(
                action=Action.MONITOR_CONNECTED_CARDS,
                route=ApprovalRoute.auto,
                reason="R6: shared origin detected",
                evidence_ids=ev_ids[:3],
                alternatives_rejected=[],
                expected_impact="Watches connected cards on same device profile for signs of coordinated fraud",
            ))

    # ── R3 customer confirmed ────────────────────────────────────────────────────────
    elif inp.customer_confirmed:
        actions.append(ActionRecommendation(
            action=Action.CLOSE_NO_FRAUD,
            route=ApprovalRoute.auto,
            reason="R3: customer confirmed the transaction",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[
                "BLOCK_CARD: not warranted — cardholder confirmed the transaction as legitimate",
            ],
            expected_impact="Closes case as legitimate, restores normal card operation",
        ))

    # ── R4 no reply ──────────────────────────────────────────────────────────────
    elif inp.no_reply:
        actions.append(ActionRecommendation(
            action=Action.MONITOR_CARD,
            route=ApprovalRoute.auto,
            reason="R4: no reply within 24 hours",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[
                "BLOCK_CARD: no cardholder confirmation of fraud — monitoring is proportionate",
            ],
            expected_impact="Flags card for heightened transaction review pending cardholder response",
        ))
        actions.append(ActionRecommendation(
            action=Action.DECLINE_TRANSACTION,
            route=ApprovalRoute.L1,
            reason="R4: decline pending authorization",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Blocks re-presentation of the disputed transaction until resolved",
        ))
        if inp.exposure_usd > 500:
            actions.append(ActionRecommendation(
                action=Action.ESCALATE_TO_ANALYST,
                route=ApprovalRoute.auto,
                reason="R4: exposure > $500, escalate",
                evidence_ids=ev_ids[:3],
                alternatives_rejected=[],
                expected_impact="Routes case to fraud analyst for manual review given high exposure",
            ))

    # ── R7 disputed but recurring ───────────────────────────────────────────────────
    elif inp.disputed_recurring:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R7: customer disputed a likely recurring charge",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Opens investigation to determine if recurring charge is legitimate or fraudulent",
        ))
        actions.append(ActionRecommendation(
            action=Action.VERIFY_WITH_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R7",
            evidence_ids=ev_ids[:2],
            alternatives_rejected=["BLOCK_CARD: R7 prohibits blocking on disputed recurring patterns"],
            expected_impact="Confirms whether customer intended to cancel or disputes the charge",
        ))
        actions.append(ActionRecommendation(
            action=Action.WARN_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R7: do not block",
            evidence_ids=[],
            alternatives_rejected=[],
            expected_impact="Informs customer of the recurring charge pattern for their awareness",
        ))

    # ── R9 undocumented coordinated ──────────────────────────────────────────────────
    elif inp.undocumented_coordinated:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R9: undocumented coordinated pattern",
            evidence_ids=ev_ids[:5],
            alternatives_rejected=[],
            expected_impact="Establishes investigation case for multi-card coordinated pattern",
        ))
        actions.append(ActionRecommendation(
            action=Action.FILE_REPORT,
            route=ApprovalRoute.L2,
            reason="R9",
            evidence_ids=ev_ids[:5],
            alternatives_rejected=["GENERATE_REPORT: R9 coordinated patterns require regulatory disclosure"],
            expected_impact="Files SAR for coordinated fraud pattern per regulatory requirement",
        ))
        actions.append(ActionRecommendation(
            action=Action.ESCALATE_TO_ANALYST,
            route=ApprovalRoute.auto,
            reason="R9",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Routes to specialist analyst for undocumented pattern classification",
        ))

    # ── R6 shared origin without denial yet ───────────────────────────────────────────
    elif inp.shared_origin and inp.fraud_probability >= 0.50:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R6: shared device/region/email across multiple cards",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Opens investigation to track the shared origin fraud ring",
        ))
        actions.append(ActionRecommendation(
            action=Action.FILE_REPORT,
            route=ApprovalRoute.L2,
            reason="R6: shared origin requires report",
            evidence_ids=ev_ids[:5],
            alternatives_rejected=["GENERATE_REPORT: shared origin across cards requires regulatory disclosure"],
            expected_impact="Files SAR covering all cards sharing this device/region profile",
        ))
        actions.append(ActionRecommendation(
            action=Action.MONITOR_CONNECTED_CARDS,
            route=ApprovalRoute.auto,
            reason="R6",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[],
            expected_impact="Watches all connected cards for further fraudulent activity",
        ))

    # ── R1 single signal, probability < 0.70 ─────────────────────────────────────────
    elif 0.15 <= inp.fraud_probability < 0.70 and inp.evidence_count <= 1:
        actions.append(ActionRecommendation(
            action=Action.VERIFY_WITH_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R1: single signal, probability < 0.70 – verify before blocking",
            evidence_ids=ev_ids[:2],
            alternatives_rejected=[
                "BLOCK_CARD: R1 requires verification before blocking on a single signal",
            ],
            expected_impact="Obtains cardholder confirmation before any disruptive action is taken",
        ))

    # ── R8 uncertain with exposure ────────────────────────────────────────────────────
    if inp.uncertain_exposed and not actions:
        actions.append(ActionRecommendation(
            action=Action.ESCALATE_TO_ANALYST,
            route=ApprovalRoute.auto,
            reason="R8: uncertain verdict with exposure > $500",
            evidence_ids=ev_ids[:3],
            alternatives_rejected=[
                "BLOCK_CARD: R8 requires analyst review before blocking on borderline evidence",
            ],
            expected_impact="Routes high-exposure uncertain case to analyst for manual risk decision",
        ))

    # ── High probability without specific rule match ──────────────────────────────────
    if not actions:
        if inp.fraud_probability >= 0.70:
            actions.append(ActionRecommendation(
                action=Action.BLOCK_CARD,
                route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
                reason="High fraud probability with supporting evidence",
                evidence_ids=ev_ids[:5],
                alternatives_rejected=[
                    "MONITOR_CARD: insufficient — fraud probability ≥ 0.70 requires stronger action",
                    "VERIFY_WITH_CUSTOMER: already attempted or not applicable at this probability level",
                ],
                expected_impact="Prevents further fraudulent charges on card with high-confidence fraud signal",
            ))
            actions.append(ActionRecommendation(
                action=Action.CREATE_CASE,
                route=ApprovalRoute.auto,
                reason="Policy §3a: create case when probability ≥ 0.30",
                evidence_ids=ev_ids[:3],
                alternatives_rejected=[],
                expected_impact="Creates official investigation record for this fraud event",
            ))
        elif inp.fraud_probability >= 0.30:
            actions.append(ActionRecommendation(
                action=Action.CREATE_CASE,
                route=ApprovalRoute.auto,
                reason="Policy §3a: probability ≥ 0.30 triggers case creation",
                evidence_ids=ev_ids[:3],
                alternatives_rejected=[],
                expected_impact="Opens investigation record while additional verification proceeds",
            ))
            actions.append(ActionRecommendation(
                action=Action.VERIFY_WITH_CUSTOMER,
                route=ApprovalRoute.auto,
                reason="R1: insufficient evidence for blocking",
                evidence_ids=ev_ids[:2],
                alternatives_rejected=[
                    "BLOCK_CARD: probability < 0.70 with limited evidence — R1 requires verification first",
                ],
                expected_impact="Obtains cardholder input to resolve borderline fraud probability",
            ))
        else:
            actions.append(ActionRecommendation(
                action=Action.ALLOW_TRANSACTION,
                route=ApprovalRoute.auto,
                reason="Low fraud probability with no contradicting signals",
                evidence_ids=[],
                alternatives_rejected=[
                    "BLOCK_CARD: probability < 0.15 — no evidence supports blocking",
                ],
                expected_impact="Allows transaction to proceed; no fraud indicators meet action threshold",
            ))

    # SAR check for R6 / high probability – ensure FILE_REPORT is in actions
    if inp.fraud_probability >= 0.70 and inp.exposure_usd > 1000:
        if not any(a.action == Action.FILE_REPORT for a in actions):
            actions.append(ActionRecommendation(
                action=Action.FILE_REPORT,
                route=ApprovalRoute.L2,
                reason="Fraud confirmed and exposure > $1,000",
                evidence_ids=ev_ids[:5],
                alternatives_rejected=["GENERATE_REPORT: exposure > $1,000 with fraud probability triggers SAR"],
                expected_impact="Files regulatory SAR for confirmed high-value fraud",
            ))

    return actions


def should_file_sar(
    actions: list[ActionRecommendation],
    exposure_usd: float,
    shared_origin: bool,
    verdict: str,
) -> tuple[bool, str]:
    """
    Policy §3a – determine whether a SAR should be filed.
    Returns (file: bool, reason: str).
    """
    has_file_report = any(a.action == Action.FILE_REPORT for a in actions)
    if not has_file_report:
        return False, "FILE_REPORT not recommended; SAR not required"

    if verdict in ("fraud",):
        if exposure_usd > 1000:
            return True, "R2: confirmed fraud with exposure > $1,000"
        if shared_origin:
            return True, "R6: confirmed fraud connected to shared device profile or card"
        return True, "Fraud confirmed and FILE_REPORT recommended"

    if verdict == "uncertain":
        return True, "R8/R9: strongly suspected; regulator disclosure warranted"

    return False, "Legitimate verdict – no SAR"


def validate_action_permission(action: Action, route: ApprovalRoute) -> tuple[bool, str]:
    """
    Policy §2 – check the route is correct for the action.
    Returns (valid: bool, message: str).
    """
    expected = get_route(action)
    if action == Action.BLOCK_CARD:
        # We can't check exposure here, so we accept both L1 and L2 for BLOCK_CARD
        if route not in (ApprovalRoute.L1, ApprovalRoute.L2):
            return False, f"BLOCK_CARD requires L1 or L2, got {route}"
        return True, "ok"
    if route != expected:
        return False, f"{action} requires {expected}, got {route}"
    return True, "ok"


def can_auto_execute(action: Action) -> bool:
    return action in _AUTO_ACTIONS
