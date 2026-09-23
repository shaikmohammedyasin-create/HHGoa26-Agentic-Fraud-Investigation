"""
LLM abstraction layer.

Used ONLY for text generation:
  - Case summary (2-6 sentences)
  - SAR narrative (6-12 sentences)

Probability scores, evidence, policy decisions, and actions are all
deterministic.  The LLM never makes those decisions.

Falls back to a template when provider = 'none' or when LLM call fails.
"""
from __future__ import annotations

import json
from datetime import datetime

from backend.config import settings
from backend.logging import get_logger

log = get_logger(__name__)


def _call_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.llm_model,
        max_tokens=512,
        temperature=settings.llm_temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _call_openai(prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=settings.llm_temperature,
    )
    return resp.choices[0].message.content.strip()


def _call_groq(prompt: str) -> str:
    import httpx
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.groq_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a professional banking fraud and AML compliance officer. "
                    "Write clear, concise, objective case summaries (2-4 sentences) or "
                    "formal Suspicious Activity Report (SAR) narratives strictly based on the provided case facts."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 512,
        "temperature": settings.llm_temperature,
    }
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def _template_summary(prompt_hint: str) -> str:
    return (
        "Investigation complete. Evidence gathered from transaction history, "
        "device records, and historical case memory. "
        "Risk and pattern assessment performed using deterministic heuristics. "
        "Next-best-action and policy route determined by the Fraud Policy engine."
    )


def _template_sar(prompt_hint: str) -> str:
    return (
        "Suspicious activity was identified based on analysis of transaction records, "
        "device profiles, billing regions, and historical case data. "
        "The activity involves transactions inconsistent with the cardholder's established history. "
        "Supporting evidence and entity identifiers are recorded in the attached case file. "
        "This report is filed in accordance with applicable regulatory requirements."
    )


def _provider_available() -> bool:
    """A real provider is configured and able to be called."""
    if settings.llm_provider == "none":
        return False
    if settings.llm_provider == "anthropic":
        return bool(settings.anthropic_api_key)
    if settings.llm_provider == "openai":
        return bool(settings.openai_api_key)
    if settings.llm_provider == "groq":
        return bool(settings.groq_api_key)
    return False


def generate_summary(prompt: str) -> tuple[str, int, bool]:
    """Returns (text, tokens_used, llm_used).

    llm_used is False whenever the text came from the deterministic template —
    the caller must not present template text as model reasoning.
    """
    if not _provider_available():
        return _template_summary(prompt), 0, False
    try:
        if settings.llm_provider == "anthropic":
            text = _call_anthropic(prompt)
        elif settings.llm_provider == "groq":
            text = _call_groq(prompt)
        else:
            text = _call_openai(prompt)
        return text, len(prompt.split()) + len(text.split()), True
    except Exception as exc:
        log.warning("llm.fallback_to_template", error=str(exc))
    return _template_summary(prompt), 0, False


def generate_sar_narrative(prompt: str) -> tuple[str, int, bool]:
    """Returns (narrative_text, tokens_used, llm_used)."""
    if not _provider_available():
        return _template_sar(prompt), 0, False
    try:
        if settings.llm_provider == "anthropic":
            text = _call_anthropic(prompt)
        elif settings.llm_provider == "groq":
            text = _call_groq(prompt)
        else:
            text = _call_openai(prompt)
        return text, len(prompt.split()) + len(text.split()), True
    except Exception as exc:
        log.warning("llm.sar.fallback", error=str(exc))
    return _template_sar(prompt), 0, False

