"""
Pattern detector.

Deterministic detection of the five known fraud patterns from README.
Returns the best-matching pattern and a confidence score for that match.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.models import FraudPattern
from backend.risk.assessment import EvidenceSignals


@dataclass
class PatternResult:
    pattern: FraudPattern
    confidence: float          # 0-1 how well the signals fit this pattern
    description: str


def _undocumented_description(sig: EvidenceSignals) -> str:
    """Two/three sentences describing an undocumented pattern from the signals."""
    links: list[str] = []
    if sig.shared_device_count:
        links.append(f"{sig.shared_device_count} other card(s) share the device profile used here")
    if sig.device_linked_fraud:
        links.append(f"the same device profile appears in {sig.device_linked_fraud} confirmed fraud case(s)")
    if sig.connected_card_fraud:
        links.append(f"{sig.connected_card_fraud} confirmed fraud case(s) on connected cards")
    if sig.new_region:
        links.append("billing region with no prior history on this card")
    joined = "; ".join(links) or "no single named shared element"

    return (
        f"Activity does not match any of the five known fraud patterns, but the evidence "
        f"shows coordinated abuse across accounts: {joined}. "
        f"It is reported as undocumented rather than forced into a known category, per policy R9."
    )


def detect_pattern(sig: EvidenceSignals, trigger_type: str = "risk_score") -> PatternResult:
    """
    Apply each pattern's heuristic, return the best match.

    Pattern rules follow README §"The five known fraud patterns".
    """
    scores: dict[FraudPattern, tuple[float, str]] = {}

    # ── 1. Card testing ───────────────────────────────────────────────────────
    # ≥3 tiny online authorizations often under $5, then a larger purchase
    if sig.card_testing_sequence and sig.small_online_count >= 3:
        scores[FraudPattern.card_testing] = (
            0.85 + min(0.10, sig.small_online_count * 0.02),
            "Three or more sub-$10 online authorizations followed by a larger purchase",
        )
    elif sig.card_testing_sequence and sig.small_online_count >= 2:
        scores[FraudPattern.card_testing] = (
            0.65,
            "Two small online authorizations followed by a larger purchase (partial card-testing signal)",
        )

    # ── 2. Card-not-present fraud ─────────────────────────────────────────────
    # Amounts/products don't fit history; burst of 2-4 online within 48h
    cnp_score = 0.0
    cnp_desc = ""
    if sig.burst_online >= 2:
        cnp_score += 0.30
        cnp_desc = f"Burst of {sig.burst_online} online transactions within 48h"
    if sig.txn_amount > 2 * sig.avg_card_amount and sig.avg_card_amount > 0:
        cnp_score += 0.15
        cnp_desc += "; amount is well above card average"
    if cnp_score >= 0.30:
        scores[FraudPattern.card_not_present_fraud] = (cnp_score, cnp_desc.lstrip("; "))

    # ── 3. Card-not-present from new device ────────────────────────────────────
    cnp_nd_score = 0.0
    cnp_nd_desc = ""
    if sig.new_device:
        cnp_nd_score += 0.30
        cnp_nd_desc = "Device marked New for this account"
    if sig.proxy_used:
        cnp_nd_score += 0.15
        cnp_nd_desc += "; proxy/anonymous connection"
    if sig.burst_online >= 1:
        cnp_nd_score += 0.15
    if cnp_nd_score >= 0.30:
        scores[FraudPattern.card_not_present_new_device] = (
            cnp_nd_score, cnp_nd_desc.lstrip("; ")
        )

    # ── 4. Out-of-region use ──────────────────────────────────────────────────
    if sig.new_region and not sig.region_streak:
        score_r = 0.50
        desc_r = "Card-present transaction in billing region with no prior history"
        if sig.prior_fraud_cases > 0:
            score_r += 0.10
        scores[FraudPattern.out_of_region_use] = (score_r, desc_r)

    # ── 5. Account takeover ───────────────────────────────────────────────────
    ato_score = 0.0
    ato_desc = ""
    if sig.mixed_channel:
        ato_score += 0.25
        ato_desc = "Mixed-channel activity inconsistent with cardholder"
    if sig.match_flag_anomaly:
        ato_score += 0.20
        ato_desc += "; match flag anomalies"
    if sig.new_device and sig.mixed_channel:
        ato_score += 0.15
        ato_desc += "; new device on multi-channel pattern"
    if ato_score >= 0.25:
        scores[FraudPattern.account_takeover] = (ato_score, ato_desc.lstrip("; "))

    if not scores:
        # R9: coordinated or repeated abuse across customers that fits none of
        # the five known patterns.  Requires cross-card/cross-device evidence,
        # not just a single weak signal.
        coordinated = (
            sig.evidence_count >= 3
            and (
                sig.shared_device_count >= 2
                or sig.connected_card_fraud > 0
                or sig.device_linked_fraud > 0
            )
        )
        if coordinated:
            return PatternResult(
                pattern=FraudPattern.undocumented,
                confidence=0.50,
                description=_undocumented_description(sig),
            )

        return PatternResult(
            pattern=FraudPattern.none,
            confidence=0.0,
            description="No known fraud pattern detectable from available signals",
        )

    best_pattern = max(scores, key=lambda p: scores[p][0])
    best_conf, best_desc = scores[best_pattern]

    return PatternResult(
        pattern=best_pattern,
        confidence=round(min(best_conf, 0.97), 3),
        description=best_desc,
    )
