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


def build_recommendations(inp: PolicyInput) -> list[ActionRecommendation]:
    """
    Apply policy rules R1-R10 in priority order and return a ranked list.
    """
    actions: list[ActionRecommendation] = []

    # R10 – never BLOCK_ALL_CARDS unless ≥2 cards confirmed fraudulent
    can_block_all = inp.connected_fraud_cards_count >= 2

    # ── R5 card testing ───────────────────────────────────────────────────────
    if inp.card_testing_detected:
        if inp.exposure_usd > 100:
            actions.append(ActionRecommendation(
                action=Action.BLOCK_CARD,
                route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
                reason="R5: card-testing sequence detected, purchase over $100 already cleared",
            ))
        else:
            actions.append(ActionRecommendation(
                action=Action.DECLINE_TRANSACTION,
                route=ApprovalRoute.L1,
                reason="R5: card-testing sequence detected",
            ))
            actions.append(ActionRecommendation(
                action=Action.STEP_UP_AUTH,
                route=ApprovalRoute.auto,
                reason="R5: require confirmation before further activity",
            ))

    # ── R2 customer denied ───────────────────────────────────────────────────
    elif inp.customer_denied:
        actions.append(ActionRecommendation(
            action=Action.BLOCK_CARD,
            route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
            reason="R2: customer denied the transaction",
        ))
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R2",
        ))
        if inp.exposure_usd > 1000 or inp.shared_origin:
            actions.append(ActionRecommendation(
                action=Action.FILE_REPORT,
                route=ApprovalRoute.L2,
                reason="R2: exposure > $1,000 or shared device/region",
            ))
        if inp.shared_origin:
            actions.append(ActionRecommendation(
                action=Action.MONITOR_CONNECTED_CARDS,
                route=ApprovalRoute.auto,
                reason="R6: shared origin detected",
            ))

    # ── R3 customer confirmed ─────────────────────────────────────────────────
    elif inp.customer_confirmed:
        actions.append(ActionRecommendation(
            action=Action.CLOSE_NO_FRAUD,
            route=ApprovalRoute.auto,
            reason="R3: customer confirmed the transaction",
        ))

    # ── R4 no reply ───────────────────────────────────────────────────────────
    elif inp.no_reply:
        actions.append(ActionRecommendation(
            action=Action.MONITOR_CARD,
            route=ApprovalRoute.auto,
            reason="R4: no reply within 24 hours",
        ))
        actions.append(ActionRecommendation(
            action=Action.DECLINE_TRANSACTION,
            route=ApprovalRoute.L1,
            reason="R4: decline pending authorization",
        ))
        if inp.exposure_usd > 500:
            actions.append(ActionRecommendation(
                action=Action.ESCALATE_TO_ANALYST,
                route=ApprovalRoute.auto,
                reason="R4: exposure > $500, escalate",
            ))

    # ── R7 disputed but recurring ─────────────────────────────────────────────
    elif inp.disputed_recurring:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R7: customer disputed a likely recurring charge",
        ))
        actions.append(ActionRecommendation(
            action=Action.VERIFY_WITH_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R7",
        ))
        actions.append(ActionRecommendation(
            action=Action.WARN_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R7: do not block",
        ))

    # ── R9 undocumented coordinated ───────────────────────────────────────────
    elif inp.undocumented_coordinated:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R9: undocumented coordinated pattern",
        ))
        actions.append(ActionRecommendation(
            action=Action.FILE_REPORT,
            route=ApprovalRoute.L2,
            reason="R9",
        ))
        actions.append(ActionRecommendation(
            action=Action.ESCALATE_TO_ANALYST,
            route=ApprovalRoute.auto,
            reason="R9",
        ))

    # ── R6 shared origin without denial yet ───────────────────────────────────
    elif inp.shared_origin and inp.fraud_probability >= 0.50:
        actions.append(ActionRecommendation(
            action=Action.CREATE_CASE,
            route=ApprovalRoute.auto,
            reason="R6: shared device/region/email across multiple cards",
        ))
        actions.append(ActionRecommendation(
            action=Action.FILE_REPORT,
            route=ApprovalRoute.L2,
            reason="R6: shared origin requires report",
        ))
        actions.append(ActionRecommendation(
            action=Action.MONITOR_CONNECTED_CARDS,
            route=ApprovalRoute.auto,
            reason="R6",
        ))

    # ── R1 single signal, probability < 0.70 ─────────────────────────────────
    elif inp.fraud_probability < 0.70 and inp.evidence_count <= 1:
        actions.append(ActionRecommendation(
            action=Action.VERIFY_WITH_CUSTOMER,
            route=ApprovalRoute.auto,
            reason="R1: single signal, probability < 0.70 – verify before blocking",
        ))

    # ── R8 uncertain with exposure ────────────────────────────────────────────
    if inp.uncertain_exposed and not actions:
        actions.append(ActionRecommendation(
            action=Action.ESCALATE_TO_ANALYST,
            route=ApprovalRoute.auto,
            reason="R8: uncertain verdict with exposure > $500",
        ))

    # ── High probability without specific rule match ──────────────────────────
    if not actions:
        if inp.fraud_probability >= 0.70:
            actions.append(ActionRecommendation(
                action=Action.BLOCK_CARD,
                route=get_route(Action.BLOCK_CARD, inp.exposure_usd),
                reason="High fraud probability with supporting evidence",
            ))
            actions.append(ActionRecommendation(
                action=Action.CREATE_CASE,
                route=ApprovalRoute.auto,
                reason="Policy §3a: create case when probability ≥ 0.30",
            ))
        elif inp.fraud_probability >= 0.30:
            actions.append(ActionRecommendation(
                action=Action.CREATE_CASE,
                route=ApprovalRoute.auto,
                reason="Policy §3a: probability ≥ 0.30 triggers case creation",
            ))
            actions.append(ActionRecommendation(
                action=Action.VERIFY_WITH_CUSTOMER,
                route=ApprovalRoute.auto,
                reason="R1: insufficient evidence for blocking",
            ))
        else:
            actions.append(ActionRecommendation(
                action=Action.ALLOW_TRANSACTION,
                route=ApprovalRoute.auto,
                reason="Low fraud probability with no contradicting signals",
            ))

    # SAR check for R6 / high probability  – ensure FILE_REPORT is in actions
    if inp.fraud_probability >= 0.70 and inp.exposure_usd > 1000:
        if not any(a.action == Action.FILE_REPORT for a in actions):
            actions.append(ActionRecommendation(
                action=Action.FILE_REPORT,
                route=ApprovalRoute.L2,
                reason="Fraud confirmed and exposure > $1,000",
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
