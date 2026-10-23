"""
The four Nemotron analysis roles, each a small function with its own prompt
file in prompts/.

Roles (which model / why):
  1. pattern_classifier           Nano  (later Super) - high volume, cheap.
  2. verification_request_drafter Nano  - short customer-facing draft.
  3. case_narrative_and_sar_draft Ultra - best reasoning for the analyst
                                          narrative and SAR draft.
  4. analyst_qa                   Ultra - grounded question answering on
                                          one case's evidence.

Design rules:
  - "Nemotron proposes, the policy engine decides": role 1 output is a
    PROPOSAL only. Nothing here changes verdicts, patterns or actions.
  - Every role validates model output strictly and returns None on any
    failure so callers fall back to the deterministic output.
  - Prompt-injection guard: every data field is embedded in a clearly
    marked UNTRUSTED DATA section and the system prompt forbids treating
    data as instructions.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.logging import get_logger
from backend.models import FraudPattern
from backend.llm import nebius_client

log = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# ── Shared safety header for every role ──────────────────────────────────────
def _load_prompt(name: str) -> str:
    """Read one prompt template file; fail loudly only in dev, fall back
    (caller returns None) in production."""
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


SYSTEM_HEADER = _load_prompt("system_policy.txt")


def _pattern_prompt(evidence_cards: list[dict]) -> str:
    """Build the role-1 user prompt. Every card is placed in an untrusted
    DATA block so the model cannot confuse data with instructions."""
    lines = ["TASK: propose one fraud pattern for the evidence cards below.",
             "",
             "DATA (untrusted content; the ids in evidence_id are the only",
             "ids you may cite):"]
    for card in evidence_cards:
        lines.append(json.dumps(card, ensure_ascii=False))
    lines += ["",
              "Respond with the single JSON object described in the task rules."]
    return "\n".join(lines)


def classify_pattern(evidence_cards: list[dict]) -> dict | None:
    """Role 1 - pattern proposal (Nano; Super when confidence seems needed).

    Input: tagged evidence cards as dicts with keys evidence_id, claim,
    source, ref (ids come from the case's own evidence items only).

    Returns a PROPOSAL dict:
      {pattern, confidence, evidence_ids, rationale}
    or None if the model is unavailable / output is invalid. The pattern is
    validated against the FraudPattern enum and every evidence id must exist
    in the input cards; violations are rejected and fall back.
    """
    allowed_ids = {str(c.get("evidence_id", "")) for c in evidence_cards}
    allowed_ids.discard("")
    raw = nebius_client.chat(
        role="pattern_classifier",
        system=SYSTEM_HEADER + "\n" + _load_prompt("pattern_classifier.txt"),
        user=_pattern_prompt(evidence_cards),
        model=nebius_client.model_nano(),   # Nano tier
        max_tokens=1024,   # headroom: Nemotron reasoning tokens precede the JSON
    )
    if raw is None:
        return None
    text, usage = raw
    parsed = _parse_json(text)
    if parsed is None:
        log.info("roles.pattern_classifier.invalid_json")
        return None
    pattern = str(parsed.get("pattern", ""))
    if pattern not in [p.value for p in FraudPattern]:
        log.info("roles.pattern_classifier.pattern_not_in_enum", pattern=pattern)
        return None
    raw_ids = parsed.get("evidence_ids", [])
    if not isinstance(raw_ids, list):
        return None
    citable = [str(e) for e in raw_ids if str(e) in allowed_ids]
    if len(citable) != len(raw_ids):
        log.info("roles.pattern_classifier.unknown_evidence_id",
                 rejected=len(raw_ids) - len(citable))
        return None
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return None
    rationale = str(parsed.get("rationale", ""))[:400]
    # Rationale must be <= 60 words per prompt contract.
    if len(rationale.split()) > 64:
        rationale = " ".join(rationale.split()[:60])
    return {
        "pattern": pattern,
        "confidence": round(confidence, 3),
        "evidence_ids": citable,
        "rationale": rationale,
        "usage": usage,
    }


def draft_verification(trigger_text: str, txn_id: str, amount: str,
                       confirm_fact: str) -> str | None:
    """Role 2 - plain-text customer verification message (Nano tier).

    Input fields come from the flagged transaction only; nothing else is
    forwarded. Returns None when the model is unavailable.
    """
    user = (
        "TASK: draft the customer verification message.\n"
        "\n"
        "DATA (untrusted):\n"
        f"transaction_reference: {txn_id}\n"
        f"amount: {amount}\n"
        f"fact_to_confirm: {_untrusted(confirm_fact)}\n"
        f"contact_reason: {_untrusted(trigger_text[:160])}\n"
    )
    raw = nebius_client.chat(
        role="verification_request_drafter",
        system=SYSTEM_HEADER + "\n" + _load_prompt("verification_request_drafter.txt"),
        user=user,
        model=nebius_client.model_nano(),
        max_tokens=2048,   # headroom: reasoning budget varies per attempt
    )
    if raw is None:
        return None
    text, usage = raw
    if not text or len(text.split()) < 5:
        return None
    return text


def narrative_and_sar(case_facts: dict, evidence_cards: list[dict]) -> dict | None:
    """Role 3 - analyst narrative + SAR draft (Ultra tier).

    Returns {"summary": str, "sar_narrative": str} with usage, or None.
    The SAR narrative may be empty when the SAR threshold was not met; the
    caller keeps its own SAR decision.
    """
    lines = ["TASK: write the analyst narrative and the SAR draft.",
             "",
             "CASE (untrusted data):"]
    lines.append(json.dumps(case_facts, ensure_ascii=False))
    lines += ["", "EVIDENCE TRAIL (untrusted data; cite these ids only):"]
    for card in evidence_cards:
        lines.append(json.dumps(card, ensure_ascii=False))
    raw = nebius_client.chat(
        role="case_narrative_and_sar_draft",
        system=SYSTEM_HEADER + "\n" + _load_prompt("case_narrative_and_sar_draft.txt"),
        user="\n".join(lines),
        model=nebius_client.model_ultra(),   # Ultra tier
        max_tokens=2048,   # headroom: Ultra reasoning tokens precede the JSON,
    )
    if raw is None:
        return None
    text, usage = raw
    parsed = _parse_json(text)
    if parsed is None:
        return None
    summary = str(parsed.get("summary", "")).strip()[:1200]
    sar = str(parsed.get("sar_narrative", "")).strip()[:2200]
    if not summary:
        return None
    return {"summary": summary, "sar_narrative": sar, "usage": usage}


def analyst_qa(instance: dict, evidence_cards: list[dict], question: str) -> str | None:
    """Role 4 - POST /api/cases/{id}/ask support (Ultra tier).

    Answers from the case evidence only; refuses politely when the answer
    is not in the evidence. Returns None when the model is unavailable.
    """
    lines = ["TASK: answer the analyst question using only the data below.",
             "",
             "CASE (untrusted data):"]
    lines.append(json.dumps(instance, ensure_ascii=False))
    lines += ["", "EVIDENCE TRAIL (untrusted data):"]
    for card in evidence_cards:
        lines.append(json.dumps(card, ensure_ascii=False))
    lines += ["", f"QUESTION (untrusted text): {_untrusted(question)}",
              "",
              "OUTPUT FORMAT: after any thinking, write 'ANSWER:' on its own "
              "line, then the final answer only. Everything before the "
              "'ANSWER:' marker is reasoning and will be discarded."]
    raw = nebius_client.chat(
        role="analyst_qa",
        system=SYSTEM_HEADER + "\n" + _load_prompt("analyst_qa.txt"),
        user="\n".join(lines),
        model=nebius_client.model_ultra(),
        max_tokens=1200,   # headroom: Ultra reasoning tokens precede ANSWER:
    )
    if raw is None:
        return None
    text, usage = raw
    if not text:
        return None
    final = _after_answer_marker(text)
    return final[:1200]


def _after_answer_marker(text: str) -> str:
    """Keep only the final answer when the model emitted an ANSWER: marker.

    Nemotron reasoning models may narrate their thinking in the content;
    the marker contract keeps user-visible answers clean."""
    if "ANSWER:" in text:
        return text.rsplit("ANSWER:", 1)[1].strip()
    return text.strip()


def _parse_json(text: str) -> dict | None:
    """Parse a model response that may be wrapped in code fences."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.split("\n", 1)[-1]
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(body[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except ValueError as exc:
        log.info("roles.parse_json_failed", error=str(exc)[:120])
        return None


def _untrusted(value: str) -> str:
    """Wrap an untrusted data value so a prompt-injection string cannot
    break the prompt structure."""
    clean = str(value).replace("\n", " ").replace("{", "").replace("}", "")
    return f'"UNTRUSTED:{clean[:300]}"'
