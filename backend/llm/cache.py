"""
On-disk LLM response cache for demo mode.

Purpose: judge traffic in DEMO_MODE consumes the user's Token Factory
credits once per (role, prompt) and then replays the stored answer, so
demo runs cost O(distinct questions) calls instead of O(total questions).

Key design:
- cache key = sha256(role + system-ish prompt content + body), computed by
  the nebius client at call time. Same question text across cases still
  differs because the case data is embedded in the prompt body.
- storage = one JSON file (dict of key -> record) with a file lock-free
  best-effort read/update pattern; data volume is tiny (judge traffic is
  capped by the daily call limit).
- disabled (no read, no write) unless settings.demo_mode is on.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from backend.config import settings
from backend.logging import get_logger

log = get_logger(__name__)

_CACHE_SCHEMA = 1


def _cache_path() -> Path:
    """Cache file lives under data/logs/ next to the JSONL call log."""
    p = Path(settings.llm_call_log_path)
    return p.with_suffix("").with_name("llm_answer_cache.json")


def make_key(role: str, user: str) -> str:
    """Stable cache key: role plus a hash of the full prompt body."""
    digest = hashlib.sha256(f"{str(_CACHE_SCHEMA)}|{user}".encode("utf-8")).hexdigest()
    return f"{role}:{digest}"


def _read_all() -> dict:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError) as exc:
        log.warning("llm_cache.read_failed", error=str(exc))
        return {}


def _write_all(entries: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("llm_cache.write_failed", error=str(exc))


def get_cached(role: str, user: str) -> dict | None:
    """Return {'text', 'usage'} for a cached call, or None."""
    if not settings.demo_mode:
        return None
    entries = _read_all()
    record = entries.get(make_key(role, user))
    if not record or "text" not in record:
        return None
    return {"text": record["text"], "usage": dict(record.get("usage", {}))}


def put_cached(role: str, user: str, text: str, usage: dict) -> None:
    """Store a successful call for demo-mode replay. No-op when not in demo."""
    if not settings.demo_mode or not text:
        return
    entries = _read_all()
    entries[make_key(role, user)] = {
        "text": text,
        "usage": dict(usage or {}),
        "ts": time.time(),
    }
    _write_all(entries)


def calls_used_today(utc_now_epoch: float | None = None) -> int:
    """Successful Token Factory calls logged since local midnight UTC."""
    from backend.llm.nebius_client import read_logs

    day = time.strftime("%Y-%m-%d", time.gmtime(utc_now_epoch or time.time()))
    count = 0
    for r in read_logs(limit=5000):
        ts = str(r.get("ts", ""))
        # Cache replays cost zero credits and never count against the cap.
        if (r.get("success") and not r.get("cached")
                and r.get("role") != "cache-replay" and ts.startswith(day)):
            count += 1
    return count
