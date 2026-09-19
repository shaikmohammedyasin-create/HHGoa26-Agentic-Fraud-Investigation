"""
GraphRAG context builder.

Combines structured graph evidence + document retrieval into a grounded
context object that the LLM (if configured) can reason over.

No raw database records are sent to the LLM.  Only selected, structured,
evidence-relevant fields reach the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.models import (
    EvidenceItem, HistoricalCase, EvidenceSource, RiskLevel,
    TransactionRecord, IdentityRecord, InvestigationCase,
)

FRAUD_POLICY_TEXT = """
FRAUD POLICY R1-R10 SUMMARY:
R1: Verify before blocking on a single signal with fraud probability < 0.70.
R2: Customer denial → BLOCK_CARD + CREATE_CASE; FILE_REPORT if exposure > $1,000 or shared device.
R3: Customer confirmation → CLOSE_NO_FRAUD.
R4: No reply within 24h → MONITOR_CARD + DECLINE_TRANSACTION; escalate if exposure > $500.
R5: Card testing (≥3 small online auths + larger purchase) → DECLINE_TRANSACTION + STEP_UP_AUTH; BLOCK_CARD if purchase > $100 already cleared.
R6: Shared device/region/email across cards → CREATE_CASE + FILE_REPORT + MONITOR_CONNECTED_CARDS.
R7: Disputed but matches recurring pattern → CREATE_CASE + VERIFY + WARN; do not block.
R8: Uncertain verdict + exposure > $500 → ESCALATE_TO_ANALYST.
R9: Undocumented coordinated pattern → CREATE_CASE + FILE_REPORT + ESCALATE.
R10: BLOCK_ALL_CARDS only when ≥2 of the customer's cards show confirmed fraud.

STOPPING RULES:
Stop when fraud probability ≥ 0.85 OR ≤ 0.15 (with ≥2 independent pieces of evidence),
or a verification response settles the question,
or further steps are unlikely to change the decision.

APPROVAL ROUTES:
auto: ALLOW, MONITOR, VERIFY, STEP_UP, WARN, CREATE_CASE, GENERATE_REPORT, ESCALATE, CLOSE_NO_FRAUD.
L1 (team lead): DECLINE_TRANSACTION; BLOCK_CARD when exposure ≤ $2,500.
L2 (fraud manager): BLOCK_CARD when exposure > $2,500; BLOCK_ALL_CARDS (always); FILE_REPORT (always).
""".strip()

FRAUD_PATTERNS_TEXT = """
KNOWN FRAUD PATTERNS:
1. card_testing: ≥3 tiny online authorizations (often <$5) then a larger purchase. Confirmed by sequence. R5.
2. card_not_present_fraud: Online use with amounts/products not matching history; burst of 2-4 in 48h. R1-R4.
3. card_not_present_new_device: Same as #2 but device is marked New for the account, sometimes via proxy. R1-R4.
4. out_of_region_use: Card-present purchases in a billing region with no prior history; distinguish single-day from multi-day trips. R2, R3.
5. account_takeover: Mixed-channel activity, device/match-flag anomalies, suggesting stolen credentials. R2.
Undocumented patterns should be described in the agent's own words rather than forced into a known category.
""".strip()


@dataclass
class GraphRAGContext:
    """Structured evidence context assembled for LLM reasoning."""
    case_id: str
    case_summary: str                              # one-paragraph trigger + subject
    flagged_transaction: dict[str, Any] = field(default_factory=dict)
    flagged_identity: dict[str, Any] = field(default_factory=dict)
    card_history_summary: str = ""
    region_history: list[dict[str, Any]] = field(default_factory=list)
    device_history: list[dict[str, Any]] = field(default_factory=list)
    similar_prior_cases: list[dict[str, Any]] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    detected_pattern: str = "none"
    fraud_probability: float = 0.0
    risk_level: str = "LOW"
    key_signals: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    fraud_policy: str = FRAUD_POLICY_TEXT
    fraud_patterns: str = FRAUD_PATTERNS_TEXT


def build_txn_dict(txn: TransactionRecord) -> dict[str, Any]:
    return {
        "txn_id": txn.txn_id,
        "ts": txn.ts.isoformat(),
        "amount_usd": txn.amount,
        "product_cd": txn.product_cd,
        "channel": txn.channel.value,
        "billing_region": txn.addr1,
        "billing_country": txn.addr2,
        "p_email": txn.p_email,
        "risk_score": txn.risk_score,
    }


def build_identity_dict(idr: IdentityRecord) -> dict[str, Any]:
    return {
        "txn_id": idr.txn_id,
        "device_type": idr.device_type,
        "device_info": idr.device_info,
        "os": idr.os,
        "browser": idr.browser,
        "screen": idr.screen,
        "device_status": idr.device_status,  # New / Found / NotFound
        "proxy": idr.proxy,
        "match_status": idr.match_status,
    }


def build_historical_case_dict(hc: HistoricalCase) -> dict[str, Any]:
    return {
        "case_id": hc.case_id,
        "outcome": hc.outcome,
        "pattern": hc.pattern,
        "exposure_usd": hc.exposure_usd,
        "n_txns": hc.n_txns,
        "connected_cards": hc.connected_card_ids,
        "opened_at": hc.opened_at.isoformat()[:10],
        "analyst_notes": hc.analyst_notes[:400],   # truncate long notes
    }


def build_context(
    case: InvestigationCase,
    flagged_txn: TransactionRecord | None,
    flagged_identity: IdentityRecord | None,
    card_history: list[TransactionRecord],
    region_history: list[dict[str, Any]],
    device_history: list[dict[str, Any]],
    prior_cases: list[HistoricalCase],
    detected_pattern: str,
) -> GraphRAGContext:
    """
    Assemble the GraphRAG context from all investigation data collected so far.
    The LLM receives a serialised version of this; raw DB rows never leave the backend.
    """
    trigger = case.trigger
    case_summary = (
        f"Case {case.case_id}: {trigger.trigger_type.value} on "
        f"{trigger.flagged_txn_id} (card {trigger.card_id}, customer {trigger.customer_id}). "
        f"{trigger.trigger_text}"
    )

    # Card history summary (last N txns)
    if card_history:
        channels = set(t.channel.value for t in card_history)
        regions = set(t.addr1 for t in card_history if t.addr1)
        amounts = [t.amount for t in card_history]
        avg_amt = sum(amounts) / len(amounts) if amounts else 0
        hist_summary = (
            f"{len(card_history)} recent transactions on this card. "
            f"Channels: {', '.join(channels)}. "
            f"Distinct billing regions: {len(regions)}. "
            f"Average amount: ${avg_amt:.2f}."
        )
    else:
        hist_summary = "No recent card history available."

    evidence_dicts = [
        {
            "evidence_id": ev.evidence_id,
            "claim": ev.claim,
            "source": ev.source.value,
            "ref": ev.ref,
            "severity": ev.severity.value,
            "confidence": ev.confidence,
        }
        for ev in case.evidence[:20]   # cap at 20 items for context length
    ]

    uncertainty_strs = [
        f"{u.question} → {u.impact}"
        for u in case.uncertainty[:5]
    ]

    return GraphRAGContext(
        case_id=case.case_id,
        case_summary=case_summary,
        flagged_transaction=build_txn_dict(flagged_txn) if flagged_txn else {},
        flagged_identity=build_identity_dict(flagged_identity) if flagged_identity else {},
        card_history_summary=hist_summary,
        region_history=region_history[:10],
        device_history=device_history[:10],
        similar_prior_cases=[build_historical_case_dict(hc) for hc in prior_cases[:5]],
        evidence_items=evidence_dicts,
        detected_pattern=detected_pattern,
        fraud_probability=case.fraud_probability,
        risk_level=case.risk_level.value,
        key_signals=case.risk_before.key_signals if case.risk_before else [],
        uncertainties=uncertainty_strs,
    )


def to_llm_prompt(ctx: GraphRAGContext, task: str = "summarize") -> str:
    """
    Render the context as a concise LLM prompt.
    Used ONLY for text generation (summary, SAR narrative).
    Deterministic signals drive probability and actions; LLM only writes.
    """
    import json

    lines = [
        f"=== FRAUD INVESTIGATION: {ctx.case_id} ===",
        "",
        "CASE:",
        ctx.case_summary,
        "",
    ]

    if ctx.flagged_transaction:
        lines.append("FLAGGED TRANSACTION:")
        lines.append(json.dumps(ctx.flagged_transaction, indent=2))
        lines.append("")

    if ctx.flagged_identity:
        lines.append("DEVICE / IDENTITY:")
        lines.append(json.dumps(ctx.flagged_identity, indent=2))
        lines.append("")

    lines.append("CARD HISTORY:")
    lines.append(ctx.card_history_summary)
    lines.append("")

    if ctx.similar_prior_cases:
        lines.append("SIMILAR PRIOR CASES:")
        for pc in ctx.similar_prior_cases:
            lines.append(f"  {pc['case_id']}: {pc['outcome']}, pattern={pc['pattern']}, "
                        f"exposure=${pc['exposure_usd']:.2f}. {pc['analyst_notes'][:200]}")
        lines.append("")

    if ctx.evidence_items:
        lines.append("EVIDENCE:")
        for ev in ctx.evidence_items:
            lines.append(f"  [{ev['severity']}] {ev['claim']}  (source={ev['source']}, ref={ev['ref']})")
        lines.append("")

    lines.append(f"ASSESSED PATTERN: {ctx.detected_pattern}")
    lines.append(f"FRAUD PROBABILITY: {ctx.fraud_probability:.2f}")
    lines.append(f"RISK LEVEL: {ctx.risk_level}")

    if ctx.key_signals:
        lines.append("KEY SIGNALS: " + "; ".join(ctx.key_signals))

    if ctx.uncertainties:
        lines.append("OPEN UNCERTAINTIES: " + "; ".join(ctx.uncertainties))

    lines.append("")
    lines.append("--- FRAUD POLICY ---")
    lines.append(ctx.fraud_policy)
    lines.append("")
    lines.append("--- KNOWN PATTERNS ---")
    lines.append(ctx.fraud_patterns)
    lines.append("")

    if task == "summarize":
        lines.append(
            "TASK: Write a 2-6 sentence analyst summary of this investigation. "
            "Be concise. Reference specific evidence IDs where relevant. "
            "Do not invent facts not listed above."
        )
    elif task == "sar_narrative":
        lines.append(
            "TASK: Write a 6-12 sentence SAR narrative (suspicious activity report). "
            "The narrative must include: WHO (customer, cards, devices), "
            "WHAT happened, WHEN (dates), WHERE (channels/regions), "
            "HOW it was carried out, WHY it is suspicious. "
            "Do not invent facts not supported by the evidence above."
        )

    return "\n".join(lines)
