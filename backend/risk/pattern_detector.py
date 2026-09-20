"""
Pattern detector — Phase D.5 hardened.

Changes vs Phase B:
- Returns ALL scored candidates (PatternResult.candidates), not just the winner.
- Returns a secondary pattern when two patterns both score strongly.
- Applies evidence-grounded tiebreakers (from README pattern definitions) rather
  than raw additive scores alone.
- PatternResult.insufficient_evidence flag when no pattern scores >= 0.25.

TIEBREAKER RULES (generalised, grounded in README definitions):

1. account_takeover vs card_not_present_new_device:
   ATO requires mixed-channel activity OR match-flag anomalies (credential theft).
   A new device alone is a CNP-new-device signal, NOT proof of credential theft.
   If new_device is the ONLY ATO-style signal, demote account_takeover.

2. card_not_present_new_device vs card_not_present_fraud (close scores):
   If new_device=True and scores differ by < 0.10: prefer card_not_present_new_device.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.models import FraudPattern, PatternCandidate
from backend.risk.assessment import EvidenceSignals


@dataclass
class PatternResult:
    pattern: FraudPattern
    confidence: float               # 0-1 calibrated confidence for primary
    description: str
    # D.5 additions
    candidates: List[PatternCandidate] = field(default_factory=list)
    secondary: FraudPattern | None = None
    secondary_confidence: float = 0.0
    secondary_description: str = ""
    insufficient_evidence: bool = False


def _undocumented_description(sig: EvidenceSignals) -> str:
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


def _score_all_patterns(
    sig: EvidenceSignals,
) -> dict[FraudPattern, tuple[float, str, list[str], list[str]]]:
    """Returns {pattern: (raw_score, description, supporting_signals, contradicting_signals)}."""
    scores: dict[FraudPattern, tuple[float, str, list[str], list[str]]] = {}

    # ── 1. Card testing ──────────────────────────────────────────────────────
    ct_score = 0.0
    ct_sup: list[str] = []
    ct_con: list[str] = []
    if sig.card_testing_sequence and sig.small_online_count >= 3:
        ct_score = 0.85 + min(0.10, sig.small_online_count * 0.02)
        ct_sup = [f"{sig.small_online_count} sub-$10 online authorizations in 2h", "card-testing sequence confirmed"]
        scores[FraudPattern.card_testing] = (ct_score, f"≥3 sub-$10 online authorizations ({sig.small_online_count}) followed by larger purchase", ct_sup, ct_con)
    elif sig.card_testing_sequence and sig.small_online_count >= 2:
        ct_score = 0.65
        ct_sup = ["2 tiny online transactions in 2h window"]
        scores[FraudPattern.card_testing] = (ct_score, "2 small online authorizations followed by a larger purchase", ct_sup, ct_con)

    # ── 2. Card-not-present fraud ─────────────────────────────────────────────
    cnp_score = 0.0
    cnp_sup: list[str] = []
    cnp_con: list[str] = []
    cnp_desc_parts: list[str] = []
    if sig.burst_online >= 2:
        cnp_score += 0.30
        cnp_desc_parts.append(f"Burst of {sig.burst_online} online transactions within 48h")
        cnp_sup.append(f"{sig.burst_online} online transactions in 48h window")
    if sig.txn_amount > 2 * sig.avg_card_amount and sig.avg_card_amount > 0:
        cnp_score += 0.15
        cnp_desc_parts.append("amount is well above card average")
        cnp_sup.append(f"Transaction ${sig.txn_amount:.2f} > 2x card average ${sig.avg_card_amount:.2f}")
    if cnp_score >= 0.30:
        if sig.new_device:
            cnp_con.append("New-device signal suggests card_not_present_new_device may be primary")
        scores[FraudPattern.card_not_present_fraud] = (cnp_score, "; ".join(cnp_desc_parts), cnp_sup, cnp_con)

    # ── 3. Card-not-present from new device ──────────────────────────────────
    cnp_nd_score = 0.0
    cnp_nd_sup: list[str] = []
    cnp_nd_con: list[str] = []
    cnp_nd_desc_parts: list[str] = []
    if sig.new_device:
        cnp_nd_score += 0.30
        cnp_nd_desc_parts.append("Device marked New for this account")
        cnp_nd_sup.append("Device status = New (id_15)")
    if sig.proxy_used:
        cnp_nd_score += 0.15
        cnp_nd_desc_parts.append("proxy/anonymous connection")
        cnp_nd_sup.append("Proxy or anonymous connection (id_23)")
    if sig.burst_online >= 1:
        cnp_nd_score += 0.15
        cnp_nd_sup.append(f"{sig.burst_online} online transactions in 48h window")
    if cnp_nd_score >= 0.30:
        if not sig.new_device:
            cnp_nd_con.append("No new-device signal; card_not_present_fraud may be more appropriate")
        scores[FraudPattern.card_not_present_new_device] = (cnp_nd_score, "; ".join(cnp_nd_desc_parts), cnp_nd_sup, cnp_nd_con)

    # ── 4. Out-of-region use ─────────────────────────────────────────────────
    if sig.new_region and not sig.region_streak:
        oor_sup = ["Card-present transaction in billing region with no prior history"]
        oor_con: list[str] = []
        score_r = 0.50
        if sig.prior_fraud_cases > 0:
            score_r += 0.10
            oor_sup.append(f"{sig.prior_fraud_cases} prior fraud case(s) on this card")
        scores[FraudPattern.out_of_region_use] = (score_r, "Card-present transaction in region with no prior history", oor_sup, oor_con)

    # ── 5. Account takeover ──────────────────────────────────────────────────
    ato_score = 0.0
    ato_sup: list[str] = []
    ato_con: list[str] = []
    ato_desc_parts: list[str] = []
    if sig.mixed_channel:
        ato_score += 0.25
        ato_desc_parts.append("Mixed-channel activity inconsistent with cardholder")
        ato_sup.append("Mixed online/in-person activity in 48h window")
    if sig.match_flag_anomaly:
        ato_score += 0.20
        ato_desc_parts.append("match flag anomalies")
        ato_sup.append("Match-status anomaly on flagged transaction (id_34)")
    if sig.new_device and sig.mixed_channel and sig.match_flag_anomaly:
        ato_score += 0.15
        ato_desc_parts.append("new device on multi-channel pattern with match anomaly")
        ato_sup.append("New device combined with mixed-channel activity and credential mismatch")
    if ato_score >= 0.25:
        if not sig.mixed_channel and not sig.match_flag_anomaly:
            ato_con.append("No mixed-channel or match-flag anomaly — ATO signal is weak")
        scores[FraudPattern.account_takeover] = (ato_score, "; ".join(ato_desc_parts), ato_sup, ato_con)

    return scores


def _apply_tiebreakers(
    scores: dict[FraudPattern, tuple[float, str, list[str], list[str]]],
    sig: EvidenceSignals,
) -> dict[FraudPattern, tuple[float, str, list[str], list[str]]]:
    """
    Evidence-grounded tiebreaker rules (generalised, from README definitions).
    These fire on signal combinations, never on case IDs.
    """
    # Tiebreaker 1: ATO vs CNP-new-device
    # Principle: A new-device signal strongly favors card_not_present_new_device
    # when there is no independent credential-theft evidence (e.g. match_flag_anomaly).
    # Mixed-channel presence alone (in-person + online) is insufficient to override CNP-new-device.
    if (
        FraudPattern.account_takeover in scores
        and FraudPattern.card_not_present_new_device in scores
        and sig.new_device
    ):
        ato_s, ato_d, ato_sup, ato_con = scores[FraudPattern.account_takeover]
        nd_s, nd_d, nd_sup, nd_con = scores[FraudPattern.card_not_present_new_device]
        if not sig.match_flag_anomaly:
            if ato_s >= nd_s:
                nd_s = ato_s + 0.05
            ato_con = list(ato_con) + [
                "New device alone or with ordinary mixed channel is insufficient for ATO without match-flag anomaly"
            ]
            nd_sup = list(nd_sup) + [
                "Tiebreaker: new_device is the dominant signal; ATO requires independent credential-theft evidence"
            ]
            scores[FraudPattern.account_takeover] = (min(ato_s, nd_s - 0.05), ato_d, ato_sup, ato_con)
            scores[FraudPattern.card_not_present_new_device] = (nd_s, nd_d, nd_sup, nd_con)
        else:
            if nd_s >= ato_s:
                ato_s = nd_s + 0.05
            ato_sup = list(ato_sup) + [
                "Tiebreaker: match-status anomaly provides independent credential-theft evidence supporting ATO"
            ]
            scores[FraudPattern.account_takeover] = (ato_s, ato_d, ato_sup, ato_con)
            scores[FraudPattern.card_not_present_new_device] = (min(nd_s, ato_s - 0.05), nd_d, nd_sup, nd_con)

    # Tiebreaker 2: CNP-new-device vs CNP-fraud
    # Principle: A burst of 2-4 online txns within 48h defines card_not_present_fraud per README.
    # Isolated unusual online purchases (< 2) from a new device favor card_not_present_new_device.
    if (
        FraudPattern.card_not_present_new_device in scores
        and FraudPattern.card_not_present_fraud in scores
        and sig.new_device
    ):
        nd_s, nd_d, nd_sup, nd_con = scores[FraudPattern.card_not_present_new_device]
        cnp_s, cnp_d, cnp_sup, cnp_con = scores[FraudPattern.card_not_present_fraud]
        if sig.burst_online >= 2:
            if cnp_s >= nd_s:
                scores[FraudPattern.card_not_present_fraud] = (
                    max(cnp_s, nd_s + 0.05),
                    cnp_d,
                    list(cnp_sup) + [
                        f"Tiebreaker: burst of {sig.burst_online} online txns defines card_not_present_fraud per README"
                    ],
                    cnp_con,
                )
                scores[FraudPattern.card_not_present_new_device] = (nd_s, nd_d, nd_sup, nd_con)
            else:
                scores[FraudPattern.card_not_present_new_device] = (
                    max(nd_s, cnp_s + 0.05),
                    nd_d,
                    list(nd_sup) + ["Tiebreaker: new_device=True differentiates from card_not_present_fraud per README"],
                    nd_con,
                )
        else:
            scores[FraudPattern.card_not_present_new_device] = (
                max(nd_s, cnp_s + 0.05),
                nd_d,
                list(nd_sup) + ["Tiebreaker: new_device=True differentiates from card_not_present_fraud per README"],
                nd_con,
            )

    return scores


def detect_pattern(sig: EvidenceSignals, trigger_type: str = "risk_score") -> PatternResult:
    """
    Score all patterns, apply tiebreakers, return primary + secondary + full candidate list.
    """
    scores = _score_all_patterns(sig)
    scores = _apply_tiebreakers(scores, sig)

    if not scores:
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
                candidates=[PatternCandidate(
                    pattern=FraudPattern.undocumented,
                    score=0.50,
                    confidence=0.50,
                    supporting_signals=[
                        f"{sig.shared_device_count} cards share device profile" if sig.shared_device_count else "",
                        f"device linked to {sig.device_linked_fraud} fraud cases" if sig.device_linked_fraud else "",
                    ],
                    description=_undocumented_description(sig),
                )],
            )

        return PatternResult(
            pattern=FraudPattern.none,
            confidence=0.0,
            description="No known fraud pattern detectable from available signals",
            insufficient_evidence=True,
        )

    # Build sorted candidate list (highest score first)
    sorted_patterns = sorted(scores.keys(), key=lambda p: scores[p][0], reverse=True)

    candidates: list[PatternCandidate] = []
    for pat in sorted_patterns:
        raw_s, desc, sup, con = scores[pat]
        candidates.append(PatternCandidate(
            pattern=pat,
            score=round(raw_s, 3),
            confidence=round(min(raw_s, 0.97), 3),
            supporting_signals=[s for s in sup if s],
            contradicting_signals=[s for s in con if s],
            description=desc,
        ))

    best_pattern = sorted_patterns[0]
    best_s, best_desc, _, _ = scores[best_pattern]

    # Secondary: runner-up if score > 0.25 and within 0.30 of primary
    secondary = None
    secondary_conf = 0.0
    secondary_desc = ""
    if len(sorted_patterns) > 1:
        runner_pat = sorted_patterns[1]
        runner_s, runner_desc, _, _ = scores[runner_pat]
        if runner_s >= 0.25 and (best_s - runner_s) <= 0.30:
            secondary = runner_pat
            secondary_conf = round(min(runner_s, 0.97), 3)
            secondary_desc = runner_desc

    return PatternResult(
        pattern=best_pattern,
        confidence=round(min(best_s, 0.97), 3),
        description=best_desc,
        candidates=candidates,
        secondary=secondary,
        secondary_confidence=secondary_conf,
        secondary_description=secondary_desc,
    )
