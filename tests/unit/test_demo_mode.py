"""
Demo-mode protections: answer cache, per-IP hourly limit, global daily cap.

Nothing here performs a live Token Factory call - the Nebius client is
always mocked, aligning with the CI test isolation contract.
"""
from __future__ import annotations

import time

import pytest

from backend.config import settings
from backend.llm import cache as llm_cache
from backend.llm import nebius_client


@pytest.fixture()
def demo_env(monkeypatch, tmp_path):
    """Short-circuit settings for demo-mode unit testing."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "llm_call_log_path", str(tmp_path / "llm_calls.jsonl"))
    cache_file = tmp_path / "llm_answer_cache.json"
    monkeypatch.setattr(llm_cache, "_cache_path", lambda: cache_file)
    return cache_file


def test_cache_disabled_outside_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(llm_cache, "_cache_path", lambda: tmp_path / "c.json")
    llm_cache.put_cached("r", "prompt", "answer", {"completion_tokens": 3})
    assert llm_cache.get_cached("r", "prompt") is None
    assert not (tmp_path / "c.json").exists()


def test_cache_roundtrip_in_demo(demo_env):
    llm_cache.put_cached("role1", "prompt body", "answer answer", {"completion_tokens": 9})
    hit = llm_cache.get_cached("role1", "prompt body")
    assert hit == {"text": "answer answer", "usage": {"completion_tokens": 9}}
    # A different prompt body generates a different hash key.
    assert llm_cache.get_cached("role1", "other prompt") is None


def test_chat_serves_cached_answer_without_network(demo_env, monkeypatch):
    # Any pre-stored recorder is returned directly; the OpenAI client path
    # must never be reached.
    llm_cache.put_cached("pattern_classifier", "same user body", "CACHED-TEXT",
                         {"prompt_tokens": 5, "completion_tokens": 7})
    monkeypatch.setattr(nebius_client, "available", lambda: True)
    called = {"n": 0}
    monkeypatch.setattr(nebius_client, "_append_log",
                        lambda rec: called.__setitem__("n", called["n"] + 1))

    text, usage = nebius_client.chat(
        "pattern_classifier", system="s", user="same user body")
    assert text == "CACHED-TEXT"
    assert usage["completion_tokens"] == 7
    # One cache-hit log row, zero network.
    assert called["n"] == 1
    from backend.llm.cache import _read_all
    replay_rows = _read_all()
    assert len(replay_rows) == 1


def test_daily_cap_fails_soft(demo_env, monkeypatch):
    monkeypatch.setattr(nebius_client, "available", lambda: True)
    monkeypatch.setattr(settings, "llm_daily_call_cap", 1)
    monkeypatch.setattr(llm_cache, "calls_used_today", lambda now_epoch=None: 5)
    logged: list = []
    monkeypatch.setattr(nebius_client, "_append_log", lambda rec: logged.append(rec))
    assert nebius_client.chat("r", "s", "u") is None
    assert logged == []   # cap hit before any network call


def test_calls_used_today_counts_only_today(demo_env):
    write_log = demo_env.parent / "llm_calls.jsonl"
    now_day = time.strftime("%Y-%m-%d", time.gmtime())
    stale_day = "2026-01-01"
    write_log.write_text("\n".join([
        f'{{"role": "r", "success": true, "ts": "{now_day}T10:00:00+00:00"}}',
        f'{{"role": "r", "success": true, "ts": "{stale_day}T10:00:00+00:00"}}',
        f'{{"role": "r", "success": false, "ts": "{now_day}T11:00:00+00:00"}}',
        f'{{"role": "cache-replay", "success": true, "ts": "{now_day}T12:00:00+00:00", "cached": true}}',
    ]), encoding="utf-8")
    # Live (non-cache-replay) successes from today only: 1
    assert llm_cache.calls_used_today() == 1


# -- Per-IP hourly limiter -----------------------------------------------------

import backend.api_limits as limits


class _FakeRequest:
    def __init__(self, ip="10.0.0.1"):
        self.client = type("C", (), {"host": ip})()


@pytest.fixture()
def fresh_limiter(monkeypatch, tmp_path):
    limits._CALLS_BY_IP.clear()
    monkeypatch.setattr(settings, "llm_calls_per_ip_per_hour", 2)
    monkeypatch.setattr(settings, "llm_daily_call_cap", 0)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(llm_cache, "calls_used_today", lambda *a, **k: 0)
    return limits


def test_allow_then_429_after_hourly_budget(fresh_limiter):
    limits.check_llm_budget(_FakeRequest())
    limits.check_llm_budget(_FakeRequest())
    with pytest.raises(fresh_limiter.RateLimitExceeded):
        limits.check_llm_budget(_FakeRequest())


def test_per_ip_isolation(fresh_limiter):
    limits.check_llm_budget(_FakeRequest(ip="a"))
    limits.check_llm_budget(_FakeRequest(ip="a"))
    limits.check_llm_budget(_FakeRequest(ip="b"))  # other IP, own budget


def test_daily_cap_raises(fresh_limiter, monkeypatch):
    monkeypatch.setattr(settings, "llm_daily_call_cap", 100)
    monkeypatch.setattr(llm_cache, "calls_used_today", lambda *a, **k: 150)
    with pytest.raises(fresh_limiter.DailyCapReached):
        limits.check_llm_budget(_FakeRequest())
