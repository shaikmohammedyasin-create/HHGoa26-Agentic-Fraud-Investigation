"""
Risk, confidence, and uncertainty assessment.

Deterministic heuristics over graph-sourced evidence.
Never calls the LLM for probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.models import (
    EvidenceItem, EvidenceSource, RiskLevel, RiskAssessment, UncertaintyItem,
    TransactionRecord, IdentityRecord, HistoricalCase,
)


@dataclass
class EvidenceSignals:
    """Collected signals ready for risk assessment."""
    # Trigger
    trigger_risk_score: float | None = None
    trigger_type: str = "risk_score"

    # Amount
    txn_amount: float = 0.0
    avg_card_amount: float = 0.0

    # Pattern signals
    card_testing_sequence: bool = False          # ≥3 tiny online + larger txn
    small_online_count: int = 0                  # count of sub-$10 online txns in 2h window
    burst_online: int = 0                        # online txns in 48h window
    new_device: bool = False                     # id_15 = New
    proxy_used: bool = False                     # id_23 is not None/empty and not "NotFound"
    new_region: bool = False                     # addr1 not in historical regions
    region_streak: bool = False                  # multi-day purchases in new region (trip signal)
    mixed_channel: bool = False                  # both online and in-person in unusual pattern
    match_flag_anomaly: bool = False             # M4/match_status anomaly

    # Historical signals
    prior_fraud_cases: int = 0                   # confirmed fraud cases for this customer/card
    prior_cleared_cases: int = 0
    device_linked_fraud: int = 0                 # fraud cases on same device profile
    connected_card_fraud: int = 0                # fraud on same device but different card

    # Customer interaction
    customer_denied: bool = False
    customer_confirmed: bool = False
    customer_no_reply: bool = False

    # Shared origin
    shared_device_count: int = 0                 # other cards on same device
    shared_region_cards: int = 0
    shared_email_cards: int = 0

    # Fraud-ring analysis (graph algorithms)
    fraud_ring_size: int = 0                     # cards in the device's connected component
    fraud_ring_fraud_cards: int = 0              # confirmed-fraud cards inside that component

    # Agent case memory (prior investigations written by this agent)
    agent_prior_investigations: int = 0          # prior agent cases on this customer/device
    agent_prior_fraud: int = 0                   # of those, confirmed fraud

    # Additional evidence outcomes (from evidence requests)
    step_up_failed: bool = False                 # step-up auth failed on new device
    step_up_passed: bool = False
    analyst_confirms_shared_fraud: bool = False
    analyst_clears_shared: bool = False
    watchlist_hit: bool = False
    watchlist_clear: bool = False

    # Evidence quality
    evidence_count: int = 0
    independent_evidence_count: int = 0          # distinct evidence FAMILIES (see independence.py)
    evidence_families: list[str] | None = None   # names of the contributing families


def compute_fraud_probability(sig: EvidenceSignals) -> tuple[float, list[dict]]:
    """
    Heuristic fraud probability 0-1 from evidence signals.

    Returns (probability, score_breakdown) where score_breakdown is a list
    of per-channel dicts for auditability.

    NOT a model output. Documented methodology per DECISIONS.md D7.
    """
    # q_i — the probability that channel i alone would produce this evidence
    channels: list[tuple[float, str, str]] = []  # (weight, channel_key, label)

    # ── Base from trigger ─────────────────────────────────────────────────────────
    if sig.trigger_type == "customer_report":
        channels.append((0.25, "trigger_customer_report", "Customer reported transaction as fraudulent"))
    elif sig.trigger_risk_score is not None:
        w = min(0.20, sig.trigger_risk_score * 0.20)
        channels.append((w, "trigger_risk_score", f"ML risk score {sig.trigger_risk_score:.2f} (weight {w:.2f})"))

    # ── Pattern signals ─────────────────────────────────────────────────────────
    if sig.card_testing_sequence:
        channels.append((0.50, "card_testing_sequence", "Card-testing sequence detected (≥3 sub-$10 online authorizations)"))
    if sig.new_device:
        channels.append((0.20, "new_device", "Device marked New for this account"))
    if sig.proxy_used:
        channels.append((0.12, "proxy_used", "Proxy or anonymous connection used"))
    if sig.new_region and not sig.region_streak:
        channels.append((0.22, "new_region", "Transaction in billing region with no prior history"))
    if sig.mixed_channel:
        channels.append((0.14, "mixed_channel", "Mixed online/in-person activity in 48h window"))
    if sig.match_flag_anomaly:
        channels.append((0.12, "match_flag_anomaly", "Match-flag anomaly on flagged transaction"))

    # Burst of online transactions
    if sig.burst_online >= 3:
        channels.append((0.18, "burst_online_3plus", f"{sig.burst_online} online transactions in 48h window"))
    elif sig.burst_online == 2:
        channels.append((0.09, "burst_online_2", "2 online transactions in 48h window"))

    # Amount anomaly
    if sig.avg_card_amount > 0 and sig.txn_amount > 3 * sig.avg_card_amount:
        channels.append((0.15, "amount_anomaly", f"Transaction amount ${sig.txn_amount:.2f} > 3x card average ${sig.avg_card_amount:.2f}"))

    # ── Historical signals ─────────────────────────────────────────────────────────
    if sig.prior_fraud_cases > 0:
        w = min(0.35, 0.15 + sig.prior_fraud_cases * 0.05)
        channels.append((w, "prior_fraud_cases", f"{sig.prior_fraud_cases} prior confirmed fraud case(s) on card/customer"))
    if sig.device_linked_fraud > 0:
        w = min(0.35, 0.15 + sig.device_linked_fraud * 0.08)
        channels.append((w, "device_linked_fraud", f"Device appears in {sig.device_linked_fraud} confirmed fraud case(s)"))
    if sig.connected_card_fraud > 0:
        w = min(0.25, 0.10 + sig.connected_card_fraud * 0.05)
        channels.append((w, "connected_card_fraud", f"{sig.connected_card_fraud} confirmed fraud case(s) on connected cards"))

    # ── Customer interaction ────────────────────────────────────────────────────────
    if sig.customer_denied:
        channels.append((0.55, "customer_denied", "Cardholder denied making the transaction"))

    # ── Additional-evidence outcomes (step-up / analyst / watchlist) ───────────────
    if sig.step_up_failed:
        channels.append((0.45, "step_up_failed", "Step-up authentication failed on the new device"))
    if sig.analyst_confirms_shared_fraud:
        channels.append((0.25, "analyst_confirms_shared_fraud", "Analyst confirms related fraud on the shared profile"))
    if sig.watchlist_hit:
        channels.append((0.20, "watchlist_hit", "External watchlist hit on linked identifiers"))

    # ── Fraud-ring / graph-algorithm signals ────────────────────────────────────────
    if sig.fraud_ring_fraud_cards >= 2:
        w = min(0.30, 0.15 + sig.fraud_ring_fraud_cards * 0.05)
        channels.append((w, "fraud_ring", f"Device component contains {sig.fraud_ring_fraud_cards} confirmed-fraud cards (ring of {sig.fraud_ring_size})"))

    # ── Agent case memory ────────────────────────────────────────────────────────
    if sig.agent_prior_fraud > 0:
        w = min(0.20, 0.10 + sig.agent_prior_fraud * 0.05)
        channels.append((w, "agent_prior_fraud", f"{sig.agent_prior_fraud} prior agent investigation(s) on this entity ended in confirmed fraud"))

    # ── Shared origin ──────────────────────────────────────────────────────────────
    if sig.shared_device_count > 1:
        w = min(0.22, 0.10 + sig.shared_device_count * 0.03)
        channels.append((w, "shared_device", f"Device shared across {sig.shared_device_count} other card(s)"))

    # ── Noisy-OR aggregation ────────────────────────────────────────────────────────
    not_fraud = 1.0
    for q, _, _ in channels:
        not_fraud *= (1.0 - q)

    # ── Clearing signals, multiplicative on P(not fraud) ─────────────────────────
    # Semantics: P(fraud) = 1 - not_fraud.  A clearing factor f > 1 multiplies
    # not_fraud, which LOWERS the fraud probability.  (Historical note: earlier
    # revisions multiplied not_fraud by factors < 1 for confirmations, which
    # raised the probability and only appeared to work because of the post-hoc
    # cap below; the direction is now correct for all clearing channels.)
    clearing: list[tuple[float, str, str]] = []
    if sig.customer_confirmed:
        not_fraud *= 1.0 / 0.60
        clearing.append((round(1.0 / 0.60, 3), "customer_confirmed", "Cardholder confirmed the transaction (strong clearing signal)"))
    if sig.step_up_passed:
        not_fraud *= 1.0 / 0.65
        clearing.append((round(1.0 / 0.65, 3), "step_up_passed", "Step-up authentication succeeded — device belongs to the cardholder"))
    if sig.analyst_clears_shared:
        not_fraud *= 1.0 / 0.80
        clearing.append((1.25, "analyst_clears_shared", "Analyst reports no related activity on the shared profile"))
    if sig.watchlist_clear:
        not_fraud *= 1.0 / 0.90
        clearing.append((round(1.0 / 0.90, 3), "watchlist_clear", "No external watchlist hits on linked identifiers"))
    if sig.region_streak:
        not_fraud *= 1.30
        clearing.append((1.30, "region_streak", "Multi-day new-region purchases consistent with legitimate travel"))
    if sig.prior_cleared_cases > 0:
        factor = 1.0 + min(0.25, sig.prior_cleared_cases * 0.08)
        not_fraud *= factor
        clearing.append((factor, "prior_cleared_cases",
                         f"{sig.prior_cleared_cases} prior cleared case(s) support legitimate use"))

    prob = 1.0 - not_fraud

    # customer confirms → CLOSE_NO_FRAUD).  The risk model score is "a reason
    # to look, never a verdict" (README §0), so it cannot outweigh a
    # confirmation on its own.  Cap the probability in the low band unless hard
    if sig.customer_confirmed and not (
        sig.card_testing_sequence or sig.device_linked_fraud or sig.connected_card_fraud
    ):
        prob = min(prob, 0.15)

    final_prob = max(0.05, min(0.97, round(prob, 3)))

    breakdown: list[dict] = []
    for q, key, label in channels:
        breakdown.append({
            "channel": key,
            "contribution": round(q, 3),
            "label": label,
            "type": "fraud_signal",
        })
    for factor, key, label in clearing:
        breakdown.append({
            "channel": key,
            "contribution": round(factor, 3),
            "label": label,
            "type": "clearing_signal",
        })
    breakdown.append({
        "channel": "total",
        "contribution": final_prob,
        "label": f"Combined fraud probability ({final_prob:.3f})",
        "type": "total",
    })

    return final_prob, breakdown


def classify_risk(probability: float) -> RiskLevel:
    if probability >= 0.75:
        return RiskLevel.critical
    if probability >= 0.55:
        return RiskLevel.high
    if probability >= 0.35:
        return RiskLevel.medium
    return RiskLevel.low


def compute_confidence(sig: EvidenceSignals, probability: float) -> float:
    """How confident are we in the probability estimate?"""
    # More independent evidence FAMILIES → higher confidence
    base = 0.3 + min(0.5, sig.independent_evidence_count * 0.12)
    # Customer interaction settles the uncertainty
    if sig.customer_denied or sig.customer_confirmed:
        base = max(base, 0.85)
    # Step-up auth outcome also settles the device question
    if sig.step_up_failed or sig.step_up_passed:
        base = max(base, 0.80)
    # Very low/high probability with little evidence: lower confidence
    if sig.independent_evidence_count < 2 and 0.35 < probability < 0.65:
        base -= 0.10
    return round(max(0.1, min(0.99, base)), 3)


def identify_uncertainties(sig: EvidenceSignals, probability: float) -> list[UncertaintyItem]:
    items: list[UncertaintyItem] = []

    if not sig.customer_denied and not sig.customer_confirmed and probability > settings.fraud_prob_stop_low:
        items.append(UncertaintyItem(
            question="Did the cardholder make this transaction?",
            impact="Customer denial raises probability significantly; confirmation closes the case",
            resolution_method="VERIFY_WITH_CUSTOMER",
        ))

    if sig.new_device and not sig.device_linked_fraud:
        items.append(UncertaintyItem(
            question="Is the new device known to the cardholder (e.g. a new phone)?",
            impact="Known device reduces probability; unknown device increases it",
            resolution_method="STEP_UP_AUTH or VERIFY_WITH_CUSTOMER",
        ))

    if sig.new_region and not sig.region_streak and not sig.customer_confirmed:
        items.append(UncertaintyItem(
            question="Was the cardholder traveling in this region?",
            impact="Travel confirmation reduces probability to near zero",
            resolution_method="VERIFY_WITH_CUSTOMER",
        ))

    if sig.burst_online >= 2 and not sig.customer_denied:
        items.append(UncertaintyItem(
            question="Can the burst of online purchases be explained (gift purchases, etc.)?",
            impact="Legitimate explanation reduces probability",
            resolution_method="VERIFY_WITH_CUSTOMER",
        ))

    return items


def build_risk_assessment(sig: EvidenceSignals) -> RiskAssessment:
    prob, breakdown = compute_fraud_probability(sig)
    risk = classify_risk(prob)
    conf = compute_confidence(sig, prob)
    unc = identify_uncertainties(sig, prob)

    signals: list[str] = []
    if sig.card_testing_sequence:
        signals.append("card-testing sequence detected")
    if sig.new_device:
        signals.append("new device for this account")
    if sig.proxy_used:
        signals.append("proxy/anonymous connection used")
    if sig.new_region and not sig.region_streak:
        signals.append("transaction in region with no prior history")
    if sig.burst_online >= 2:
        signals.append(f"{sig.burst_online} online transactions in 48h window")
    if sig.prior_fraud_cases:
        signals.append(f"{sig.prior_fraud_cases} prior confirmed fraud case(s) on card/customer")
    if sig.device_linked_fraud:
        signals.append(f"device also used in {sig.device_linked_fraud} confirmed fraud case(s)")
    if sig.customer_denied:
        signals.append("cardholder denied making the transaction")
    if sig.customer_confirmed:
        signals.append("cardholder confirmed the transaction")
    if sig.step_up_failed:
        signals.append("step-up authentication failed on the new device")
    if sig.step_up_passed:
        signals.append("step-up authentication succeeded on the new device")
    if sig.fraud_ring_fraud_cards >= 2:
        signals.append(f"device component contains {sig.fraud_ring_fraud_cards} confirmed-fraud cards")
    if sig.agent_prior_fraud:
        signals.append(f"{sig.agent_prior_fraud} prior agent investigation(s) ended in confirmed fraud")
    if sig.watchlist_hit:
        signals.append("external watchlist hit on linked identifiers")

    return RiskAssessment(
        fraud_probability=prob,
        risk_level=risk,
        confidence=conf,
        key_signals=signals,
        uncertainty_items=unc,
        score_breakdown=breakdown,
    )


def should_request_more_evidence(
    risk: RiskAssessment,
    sig: EvidenceSignals,
    evidence_requests_so_far: int,
    max_requests: int,
) -> bool:
    """
    Policy §5 and 'stopping' criterion.

    Request more evidence only if it is decision-relevant and within limits.
    """
    if evidence_requests_so_far >= max_requests:
        return False
    if risk.uncertainty_items and len(risk.uncertainty_items) > 0:
        prob = risk.fraud_probability
        # Borderline: inside the stopping band, so neither the fraud nor the
        # legitimate stopping criterion is met.  The band edges (0.15 / 0.85)
        # are the same ones used for the verdict thresholds, so "borderline"
        # means exactly "no defensible decision yet".
        if settings.fraud_prob_stop_low < prob < settings.fraud_prob_stop_high:
            return True
        # High probability but no customer contact yet: still useful to verify
        if prob >= settings.fraud_prob_stop_high and not sig.customer_denied \
                and not sig.customer_confirmed:
            return True
    return False
