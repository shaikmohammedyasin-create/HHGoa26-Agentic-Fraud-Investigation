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

    # Evidence quality
    evidence_count: int = 0
    independent_evidence_count: int = 0          # distinct source types


def compute_fraud_probability(sig: EvidenceSignals) -> float:
    """
    Heuristic fraud probability 0-1 from evidence signals.

    NOT a model output. Documented methodology per DECISIONS.md D7.

    Aggregation is a noisy-OR over independent evidence channels rather than a
    raw weighted sum: P(fraud) = 1 - prod_i (1 - q_i).  This keeps the score
    sub-additive, so each additional signal raises the probability by less than
    the last and the score does not saturate at the clamp the moment two strong
    signals co-occur.  Discrimination between fraud cases is preserved, which
    matters because the README scores this field for calibration.

    Clearing signals are applied multiplicatively (they reduce the probability
    that the positive evidence indicates fraud), not by subtracting a constant.
    """
    # q_i — the probability that channel i alone would produce this evidence
    channels: list[float] = []

    # ── Base from trigger ────────────────────────────────────────────────────
    if sig.trigger_type == "customer_report":
        channels.append(0.25)                  # customer already flagged it
    elif sig.trigger_risk_score is not None:
        # Risk score is correlated, not definitive (README §0)
        channels.append(min(0.20, sig.trigger_risk_score * 0.20))

    # ── Pattern signals ──────────────────────────────────────────────────────
    if sig.card_testing_sequence:
        channels.append(0.50)
    if sig.new_device:
        channels.append(0.20)
    if sig.proxy_used:
        channels.append(0.12)
    if sig.new_region and not sig.region_streak:
        channels.append(0.22)
    if sig.mixed_channel:
        channels.append(0.14)
    if sig.match_flag_anomaly:
        channels.append(0.12)

    # Burst of online transactions (CNP burst)
    if sig.burst_online >= 3:
        channels.append(0.18)
    elif sig.burst_online == 2:
        channels.append(0.09)

    # Amount anomaly
    if sig.avg_card_amount > 0 and sig.txn_amount > 3 * sig.avg_card_amount:
        channels.append(0.15)

    # ── Historical signals ────────────────────────────────────────────────────
    if sig.prior_fraud_cases > 0:
        channels.append(min(0.35, 0.15 + sig.prior_fraud_cases * 0.05))
    if sig.device_linked_fraud > 0:
        channels.append(min(0.35, 0.15 + sig.device_linked_fraud * 0.08))
    if sig.connected_card_fraud > 0:
        channels.append(min(0.25, 0.10 + sig.connected_card_fraud * 0.05))

    # ── Customer interaction ──────────────────────────────────────────────────
    if sig.customer_denied:
        channels.append(0.55)

    # ── Shared origin ─────────────────────────────────────────────────────────
    if sig.shared_device_count > 1:
        channels.append(min(0.22, 0.10 + sig.shared_device_count * 0.03))

    # ── Noisy-OR aggregation ────────────────────────────────────────────────
    not_fraud = 1.0
    for q in channels:
        not_fraud *= (1.0 - q)

    # ── Clearing signals, multiplicative ──────────────────────────────────────
    if sig.customer_confirmed:
        not_fraud *= 0.60                       # strong clearing signal
    if sig.region_streak:
        not_fraud *= 1.30                       # multi-day new region ≈ a trip
    if sig.prior_cleared_cases > 0:
        not_fraud *= (1.0 + min(0.25, sig.prior_cleared_cases * 0.08))

    prob = 1.0 - not_fraud

    # A cardholder confirmation settles the primary question (policy R3:
    # customer confirms → CLOSE_NO_FRAUD).  The risk model score is "a reason
    # to look, never a verdict" (README §0), so it cannot outweigh a
    # confirmation on its own.  Cap the probability in the low band unless hard
    # contradictory evidence (a denial-corroborating pattern signal) is present.
    if sig.customer_confirmed and not (
        sig.card_testing_sequence or sig.device_linked_fraud or sig.connected_card_fraud
    ):
        prob = min(prob, 0.15)

    return max(0.05, min(0.97, round(prob, 3)))


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
    # More independent evidence sources → higher confidence
    base = 0.3 + min(0.5, sig.independent_evidence_count * 0.12)
    # Customer interaction settles the uncertainty
    if sig.customer_denied or sig.customer_confirmed:
        base = max(base, 0.85)
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
    prob = compute_fraud_probability(sig)
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

    return RiskAssessment(
        fraud_probability=prob,
        risk_level=risk,
        confidence=conf,
        key_signals=signals,
        uncertainty_items=unc,
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
