"""
Nebius Token Factory client (NVIDIA Nemotron models).

One small client that every Nemotron role goes through:

  - Reads NEBIUS_API_KEY / NEBIUS_BASE_URL / NEBIUS_MODEL_* from settings.
  - OpenAI-compatible chat.completions (Token Factory endpoint).
  - Timeout LLM_TIMEOUT_SECONDS (30s), 2 retries with exponential backoff.
  - Temperature 0.1 everywhere (deterministic-ish analysis output).
  - Every call is logged to a JSONL file: role, model, latency_ms,
    prompt_tokens, completion_tokens, success / failure.
  - On ANY failure it returns None so the calling role can fall back to the
    deterministic output. The API must never crash or 503 because the LLM is
    down.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.logging import get_logger

log = get_logger(__name__)


def available() -> bool:
    """True only when a Token Factory key is configured."""
    return bool(settings.nebius_api_key and settings.nebius_base_url)


def model_nano() -> str:
    """Fast/cheap tier: high-volume classification and short drafts."""
    return settings.nebius_model_nano


def model_super() -> str:
    """Mid tier: classification when Nano is too weak."""
    return settings.nebius_model_super


def model_ultra() -> str:
    """Top tier: narrative generation and analyst Q&A."""
    return settings.nebius_model_ultra


def _append_log(record: dict) -> None:
    """Append one JSONL line; logging must never break the calling path."""
    try:
        path = Path(settings.llm_call_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning("nebius.log_write_failed", error=str(exc))


def read_logs(limit: int = 200) -> list[dict]:
    """Return the most recent call-log records (oldest first)."""
    path = Path(settings.llm_call_log_path)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines[-limit:]]
    except Exception as exc:
        log.warning("nebius.log_read_failed", error=str(exc))
        return []


def log_summary() -> dict:
    """Aggregate the JSONL log for the /api/llm/status endpoint."""
    records = read_logs(limit=2000)
    calls = len(records)
    ok = sum(1 for r in records if r.get("success"))
    prompt_tokens = sum(int(r.get("prompt_tokens") or 0) for r in records)
    completion_tokens = sum(int(r.get("completion_tokens") or 0) for r in records)
    latency = [float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None]
    by_role: dict[str, int] = {}
    for r in records:
        by_role[r.get("role", "?")] = by_role.get(r.get("role", "?"), 0) + 1
    return {
        "available": available(),
        "calls_logged": calls,
        "successes": ok,
        "failures": calls - ok,
        "prompt_tokens_total": prompt_tokens,
        "completion_tokens_total": completion_tokens,
        "latency_ms_p50": _percentile(latency, 0.5),
        "latency_ms_p95": _percentile(latency, 0.95),
        "by_role": by_role,
        "base_url": settings.nebius_base_url,
        "models": {
            "nano": model_nano(),
            "super": model_super(),
            "ultra": model_ultra(),
        },
    }


def _percentile(sorted_input: list[float], q: float) -> float | None:
    """Simple percentile on a plain list (input copied and sorted here)."""
    if not sorted_input:
        return None
    values = sorted(sorted_input)
    idx = min(int(q * (len(values) - 1) + 0.5), len(values) - 1)
    return round(values[idx], 1)


def chat(role: str, system: str, user: str, model: str | None = None,
         max_tokens: int = 1024) -> tuple[str, dict] | None:
    """One Token Factory completion.

    Returns (text, usage) where usage = {prompt_tokens, completion_tokens},
    or None on any failure (auth error, timeout, rate limit, bad response).
    Callers must treat None as the fallback-signal, never as a crash.
    """
    if not available():
        log.info("nebius.skipped_no_key", role=role)
        return None
    chosen_model = model or model_nano()
    started = time.perf_counter()

    # Demo-mode protections: replay stored answers before spending credits.
    from backend.llm import cache as llm_cache
    cached = llm_cache.get_cached(role, user)
    if cached:
        log.info("nebius.cache_hit", role=role)
        latency = round((time.perf_counter() - started) * 1000, 1)
        usage_out = {"prompt_tokens": cached["usage"].get("prompt_tokens", 0),
                     "completion_tokens": cached["usage"].get("completion_tokens", 0)}
        _append_log({"role": role, "model": "cache-replay", "latency_ms": latency,
                     "prompt_tokens": 0, "completion_tokens": 0,
                     "success": True, "attempt": 0, "cached": True,
                     "ts": datetime.now(timezone.utc).isoformat()})
        return cached["text"], usage_out
    # Global daily credit cap: fail soft to deterministic output, never crash.
    daily_used = llm_cache.calls_used_today()
    if settings.llm_daily_call_cap and daily_used >= settings.llm_daily_call_cap:
        log.warning("nebius.daily_cap_reached", role=role, used=daily_used,
                    cap=settings.llm_daily_call_cap)
        return None

    from openai import OpenAI
    client = OpenAI(
        api_key=settings.nebius_api_key,
        base_url=settings.nebius_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.nebius_max_retries,
    )

    attempt = 0
    last_error = ""
    while attempt <= settings.nebius_max_retries:
        try:
            resp = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=settings.llm_temperature,
            )
            text = (resp.choices[0].message.content or "").strip()
            usage = resp.usage
            usage_out = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            _append_log({
                "role": role, "model": chosen_model, "latency_ms": latency_ms,
                "prompt_tokens": usage_out["prompt_tokens"],
                "completion_tokens": usage_out["completion_tokens"],
                "success": True, "attempt": attempt,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            log.info("nebius.call_ok", role=role, model=chosen_model,
                     latency_ms=latency_ms, prompt_tokens=usage_out["prompt_tokens"],
                     completion_tokens=usage_out["completion_tokens"])
            # Demo mode stores the answer for cost-free replay later.
            llm_cache.put_cached(role, user, text, usage_out)
            return text, usage_out
        except Exception as exc:
            last_error = str(exc)
            log.warning("nebius.attempt_failed", role=role, model=chosen_model,
                        attempt=attempt, error=last_error[:300])
            attempt += 1
            if attempt <= settings.nebius_max_retries:
                time.sleep(0.5 * (2 ** attempt))

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    _append_log({
        "role": role, "model": chosen_model, "latency_ms": latency_ms,
        "prompt_tokens": 0, "completion_tokens": 0,
        "success": False, "error": last_error[:300],
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    return None
