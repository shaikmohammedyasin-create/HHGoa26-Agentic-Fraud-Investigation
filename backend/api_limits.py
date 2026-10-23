"""
Simple in-process per-IP rate limiter for LLM-touching endpoints.

Single-worker uvicorn only (the deployment for judges is one worker by
design, SQLite does not support more): state lives in module memory and
is cheap. Tiered rejection the judge sees:

429 + "Hourly question limit reached — try again in one hour."  when the
per-IP hourly budget is spent, 503 + daily-cap notice when the global
Token Factory budget is spent.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from backend.config import settings
from backend.llm import cache as llm_cache


class RateLimitExceeded(Exception):
    """Caller sent too many requests in the hour window."""


def _client_ip(request) -> str:
    if getattr(request, "client", None) and request.client.host:
        return request.client.host
    return "unknown"


def check_llm_budget(request) -> None:
    """Raise the first exceeded budget tier for this request.

    Call at the top of every endpoint that may trigger a Token Factory
    call. In demo mode the cache answers mostly come free, so the hourly
    window lives on.
    """
    ip = _client_ip(request)
    now = time.time()
    hour_window = 3600.0

    hits: deque = _CALLS_BY_IP[ip]
    while hits and now - hits[0] > hour_window:
        hits.popleft()
    if len(hits) >= settings.llm_calls_per_ip_per_hour:
        raise RateLimitExceeded(
            "Hourly question limit reached. Try again in one hour.")
    hits.append(now)

    cap = settings.llm_daily_call_cap
    if cap and llm_cache.calls_used_today() >= cap:
        raise DailyCapReached()


class DailyCapReached(Exception):
    """Global daily Token Factory budget is spent."""


_CALLS_BY_IP: dict[str, deque] = defaultdict(deque)
