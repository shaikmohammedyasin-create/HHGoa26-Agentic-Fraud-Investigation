"""
Evidence-gap engine — decides WHAT evidence to request, not just WHETHER.

For a borderline investigation the agent enumerates candidate evidence
requests, scores each by expected decision impact (information value), and
selects the highest-value request that is policy-approved and obtainable.

Information value semantics
---------------------------
For each candidate we ask: "if this evidence came back pointing either way,
could the recommended action set change, and by how much?"  Concretely:

  1. Model the two plausible outcomes of the request (e.g. customer denies /
     customer confirms).
  2. Recompute the resulting fraud probability under each outcome using the
     real Noisy-OR channels (backend.risk.assessment.compute_fraud_probability
     on a mutated EvidenceSignals copy — no duplicated heuristics).
  3. Build the policy action set for each outcome.
  4. The information value is the symmetric difference between the two action
     sets, weighted by action severity — evidence that would flip a BLOCK_CARD
     into a CLOSE_NO_FRAUD is worth more than evidence that shuffles two
     monitoring actions.
  5. Requests whose outcomes converge on the same action set (value ≈ 0) are
     suppressed: asking them cannot change the decision, so we don't ask.

This keeps the loop deterministic, auditable, and honest: the rationale recorded
on the EvidenceRequest states which hypotheses the evidence could flip and what
each outcome would produce.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace as dc_replace
from typing import Any

from backend.models import (
    Action, ApprovalRoute, EvidenceRequestType, FraudPattern, RiskLevel,
)
from backend.risk.assessment import EvidenceSignals, compute_fraud_probability
from backend.policies.engine import PolicyInput, build_recommendations
from backend.logging import get_logger

log = get_logger(__name__)

# Relative severity of each action, used to weight decision impact.  This is
# NOT a new policy table — it only ranks how far apart two action sets are.
_ACTION_SEVERITY: dict[Action, float] = {
    Action.BLOCK_ALL_CARDS: 1.0,
    Action.FILE_REPORT: 0.9,
    Action.BLOCK_CARD: 0.8,
    Action.DECLINE_TRANSACTION: 0.7,
    Action.ESCALATE_TO_ANALYST: 0.5,
    Action.STEP_UP_AUTH: 0.4,
    Action.MONITOR_CONNECTED_CARDS: 0.3,
    Action.MONITOR_CARD: 0.25,
    Action.CREATE_CASE: 0.3,
    Action.WARN_CUSTOMER: 0.2,
    Action.VERIFY_WITH_CUSTOMER: 0.2,
    Action.CLOSE_NO_FRAUD: 0.6,
    Action.ALLOW_TRANSACTION: 0.1,
    Action.GENERATE_REPORT: 0.1,
}


@dataclass
class EvidenceCandidate:
    """A possible evidence request the agent could make."""
    type: EvidenceRequestType
    question: str
    outcome_yes: str                 # human-readable outcome A
    outcome_no: str                  # human-readable outcome B
    # Mutation applied to EvidenceSignals when the outcome is "helps fraud"
    signals_fraud_side: dict[str, Any] = field(default_factory=dict)
    # Mutation applied when the outcome is "helps legitimate"
    signals_legit_side: dict[str, Any] = field(default_factory=dict)
    # Policy-gating hook: under what conditions this request is allowed at all
    requires: dict[str, Any] = field(default_factory=dict)
    # Higher = cheaper/faster evidence source; small tie-breaker influence
    cost_penalty: float = 0.0


def _action_set_distance(a: list[Action], b: list[Action]) -> float:
    """Symmetric-difference distance between two action sets, severity-weighted."""
    sa, sb = set(a), set(b)
    added = sb - sa
    removed = sa - sb
    # Weight the difference by the max severity moved in each direction.
    sev = 0.0
    if added:
        sev += max((_ACTION_SEVERITY.get(x, 0.3) for x in added), default=0.3)
    if removed:
        sev += max((_ACTION_SEVERITY.get(x, 0.3) for x in removed), default=0.3)
    # Identical sets → 0 distance
    if not added and not removed:
        return 0.0
    return min(1.0, sev / 2.0)


def _actions_for(sig: EvidenceSignals, exposure_usd: float,
                 card_testing: bool, shared_origin: bool,
                 connected_fraud_cards: int, undocumented: bool) -> list[Action]:
    """Run the policy engine on a hypothetical signal state."""
    prob, _ = compute_fraud_probability(sig)
    pol = PolicyInput(
        fraud_probability=prob,
        exposure_usd=exposure_usd,
        customer_denied=sig.customer_denied,
        customer_confirmed=sig.customer_confirmed,
        no_reply=sig.customer_no_reply,
        card_testing_detected=card_testing,
        shared_origin=shared_origin,
        disputed_recurring=False,
        uncertain_exposed=(0.15 < prob < 0.85 and exposure_usd > 500),
        undocumented_coordinated=undocumented,
        connected_fraud_cards_count=connected_fraud_cards,
        evidence_count=sig.evidence_count,
    )
    return [rec.action for rec in build_recommendations(pol)]


def _simulated_reply(candidate: EvidenceCandidate, fraud_side: bool) -> str:
    """Deterministic, clearly-labelled synthetic replies per request type."""
    if candidate.type == EvidenceRequestType.customer_validation:
        if fraud_side:
            return ("Customer states they did not make these purchases "
                    "and still has the card in their possession.")
        return ("Customer confirms they made the purchase / were traveling "
                "in the region during the dates in question.")
    if candidate.type == EvidenceRequestType.step_up_auth:
        if fraud_side:
            return "Step-up authentication failed: device not recognized by the cardholder."
        return "Step-up authentication succeeded: cardholder authenticated on the new device."
    if candidate.type == EvidenceRequestType.analyst_info:
        if fraud_side:
            return "Analyst confirms related fraud activity on the shared device profile."
        return "Analyst finds no additional suspicious activity on the shared device profile."
    # external_watchlist
    if fraud_side:
        return "External watchlist hit: device/email linked to a recent fraud report."
    return "No external watchlist hits for the linked identifiers."


def build_candidates(sig: EvidenceSignals, exposure_usd: float,
                     card_testing: bool, shared_origin: bool,
                     connected_fraud_cards: int, undocumented: bool) -> list[EvidenceCandidate]:
    """
    Enumerate the evidence requests that are *plausible* for this case.
    Whether each one is worth asking is decided by information value, not here.
    """
    candidates: list[EvidenceCandidate] = []

    # 1. Customer validation — resolves the central ownership question.
    #    Only meaningful when the customer has not already spoken.
    if not (sig.customer_denied or sig.customer_confirmed or sig.customer_no_reply):
        candidates.append(EvidenceCandidate(
            type=EvidenceRequestType.customer_validation,
            question="Did you make this transaction?",
            outcome_yes="Customer denies making the transaction",
            outcome_no="Customer confirms making the transaction / legitimate context",
            signals_fraud_side={"customer_denied": True},
            signals_legit_side={"customer_confirmed": True},
            requires={},
            cost_penalty=0.0,
        ))

    # 2. Step-up authentication — distinguishes ATO/takeover from legitimate
    #    new-device use.  Only relevant when a new-device signal exists.
    if sig.new_device and not sig.customer_confirmed:
        candidates.append(EvidenceCandidate(
            type=EvidenceRequestType.step_up_auth,
            question="Can the cardholder authenticate on the new device (step-up auth)?",
            outcome_yes="Authentication fails — device unknown to cardholder",
            outcome_no="Authentication succeeds — device is the cardholder's",
            signals_fraud_side={"step_up_failed": True, "customer_denied": False},
            signals_legit_side={"step_up_passed": True, "customer_confirmed": False},
            requires={"new_device": True},
            cost_penalty=0.05,
        ))

    # 3. Analyst info — additional context on shared infrastructure.
    if shared_origin and not sig.customer_denied:
        candidates.append(EvidenceCandidate(
            type=EvidenceRequestType.analyst_info,
            question="Does the analyst have additional context on the shared device profile?",
            outcome_yes="Analyst reports related fraud on the shared profile",
            outcome_no="Analyst reports no related activity",
            signals_fraud_side={"analyst_confirms_shared_fraud": True},
            signals_legit_side={"analyst_clears_shared": True},
            requires={"shared_origin": True},
            cost_penalty=0.10,
        ))

    # 4. External watchlist — only when coordinated/network indicators exist.
    if (sig.shared_device_count > 0 or sig.device_linked_fraud > 0
            and not sig.customer_confirmed):
        candidates.append(EvidenceCandidate(
            type=EvidenceRequestType.external_watchlist,
            question="Check external fraud watchlists for the linked device/email identifiers.",
            outcome_yes="Watchlist hit on linked identifiers",
            outcome_no="No watchlist hits",
            signals_fraud_side={"watchlist_hit": True},
            signals_legit_side={"watchlist_clear": True},
            requires={},
            cost_penalty=0.15,
        ))

    return candidates


def evaluate_candidates(
    sig: EvidenceSignals,
    exposure_usd: float,
    card_testing: bool,
    shared_origin: bool,
    connected_fraud_cards: int,
    undocumented: bool,
) -> list[dict[str, Any]]:
    """
    Score every candidate by expected decision impact.

    Returns a list of dicts sorted by information value (descending):
      { candidate, info_value, decision_relevance, fraud_side_actions,
        legit_side_actions, fraud_side_prob, legit_side_prob }
    """
    base_actions = _actions_for(
        sig, exposure_usd, card_testing, shared_origin,
        connected_fraud_cards, undocumented,
    )
    scored: list[dict[str, Any]] = []

    for cand in build_candidates(
        sig, exposure_usd, card_testing, shared_origin,
        connected_fraud_cards, undocumented,
    ):
        # Hypothetical: evidence points toward fraud
        sig_fraud = dc_replace(sig, **cand.signals_fraud_side)
        # Hypothetical: evidence points toward legitimate
        sig_legit = dc_replace(sig, **cand.signals_legit_side)

        prob_f, _ = compute_fraud_probability(sig_fraud)
        prob_l, _ = compute_fraud_probability(sig_legit)

        actions_f = _actions_for(
            sig_fraud, exposure_usd, card_testing, shared_origin,
            connected_fraud_cards, undocumented,
        )
        actions_l = _actions_for(
            sig_l := sig_legit, exposure_usd, card_testing, shared_origin,
            connected_fraud_cards, undocumented,
        )

        # Value = how far the two possible worlds diverge from each other,
        # relative to today's action set.  If both outcomes produce the same
        # actions, the evidence has no decision value.
        divergence = _action_set_distance(actions_f, actions_l)
        # Also credit evidence that would settle a currently-uncertain case
        # into a decisive one, even if the action set barely moves.
        decisiveness = 0.0
        base_prob, _ = compute_fraud_probability(sig)
        if 0.15 < base_prob < 0.85:
            if prob_f >= 0.85 or prob_l <= 0.15:
                decisiveness = 0.25

        value = min(1.0, divergence + decisiveness - cand.cost_penalty)

        scored.append({
            "candidate": cand,
            "info_value": round(value, 3),
            "decision_relevance": (
                f"Outcome A ({cand.outcome_yes}) -> {', '.join(a.value for a in actions_f) or 'no action'} "
                f"(p={prob_f:.2f}); "
                f"Outcome B ({cand.outcome_no}) -> {', '.join(a.value for a in actions_l) or 'no action'} "
                f"(p={prob_l:.2f})"
            ),
            "fraud_side_actions": [a.value for a in actions_f],
            "legit_side_actions": [a.value for a in actions_l],
            "fraud_side_prob": round(prob_f, 3),
            "legit_side_prob": round(prob_l, 3),
        })

    scored.sort(key=lambda s: s["info_value"], reverse=True)
    return scored


def select_evidence_request(
    sig: EvidenceSignals,
    exposure_usd: float,
    card_testing: bool,
    shared_origin: bool,
    connected_fraud_cards: int,
    undocumented: bool,
    min_info_value: float = 0.25,
) -> dict[str, Any] | None:
    """
    Pick the single best evidence request, or None when no request would
    materially change the decision (the agent should NOT ask).
    """
    scored = evaluate_candidates(
        sig, exposure_usd, card_testing, shared_origin,
        connected_fraud_cards, undocumented,
    )
    for s in scored:
        if s["info_value"] >= min_info_value:
            return s
    if scored:
        log.info("evidence_gap.no_high_value_request",
                 best_value=scored[0]["info_value"])
    return None


def simulate_response(candidate_type: EvidenceRequestType, sig: EvidenceSignals,
                      trigger_type: str) -> str:
    """
    Deterministic synthetic response used in `simulated` mode (benchmarks).
    Mirrors the previous documented heuristics and is always flagged as
    simulated via EvidenceRequest.origin.
    """
    if candidate_type == EvidenceRequestType.step_up_auth:
        if sig.device_linked_fraud or sig.card_testing_sequence:
            return _simulated_reply(
                EvidenceCandidate(
                    type=candidate_type, question="", outcome_yes="", outcome_no=""),
                fraud_side=True)
        return _simulated_reply(
            EvidenceCandidate(
                type=candidate_type, question="", outcome_yes="", outcome_no=""),
            fraud_side=False)

    if candidate_type == EvidenceRequestType.analyst_info:
        return _simulated_reply(
            EvidenceCandidate(
                type=candidate_type, question="", outcome_yes="", outcome_no=""),
            fraud_side=bool(sig.device_linked_fraud))

    if candidate_type == EvidenceRequestType.external_watchlist:
        return _simulated_reply(
            EvidenceCandidate(
                type=candidate_type, question="", outcome_yes="", outcome_no=""),
            fraud_side=bool(sig.device_linked_fraud or sig.shared_device_count >= 2))

    # customer_validation (default)
    if sig.card_testing_sequence or sig.device_linked_fraud:
        return ("Customer states they did not make these purchases "
                "and still has the card in their possession.")
    if sig.region_streak:
        return ("Customer confirms they were traveling in this region "
                "during the dates in question.")
    if trigger_type == "customer_report":
        return ("Customer reiterates they did not make this purchase "
                "and requests it be investigated.")
    return "No response received within the 24-hour window."


def apply_response_to_signals(sig: EvidenceSignals,
                              request_type: EvidenceRequestType,
                              response: str) -> EvidenceSignals:
    """
    Mutate a copy of the signals according to a received response.
    Returns the updated copy.  Used for both simulated and human-in-loop modes.
    """
    text = (response or "").lower()
    updates: dict[str, Any] = {}

    if request_type == EvidenceRequestType.customer_validation:
        if any(p in text for p in ("did not", "never made", "reiterates they did not",
                                   "not make these")):
            updates["customer_denied"] = True
        elif any(p in text for p in ("confirms", "traveling", "i made", "was mine")):
            updates["customer_confirmed"] = True
        elif "no response" in text or "no reply" in text:
            updates["customer_no_reply"] = True
        else:
            updates["customer_no_reply"] = True

    elif request_type == EvidenceRequestType.step_up_auth:
        if "failed" in text or "not recognized" in text:
            updates["step_up_failed"] = True
        else:
            updates["step_up_passed"] = True

    elif request_type == EvidenceRequestType.analyst_info:
        if "confirm" in text and "fraud" in text:
            updates["analyst_confirms_shared_fraud"] = True
        else:
            updates["analyst_clears_shared"] = True

    elif request_type == EvidenceRequestType.external_watchlist:
        if "hit" in text and "no " not in text[:4]:
            updates["watchlist_hit"] = True
        else:
            updates["watchlist_clear"] = True

    return dc_replace(sig, **updates)
