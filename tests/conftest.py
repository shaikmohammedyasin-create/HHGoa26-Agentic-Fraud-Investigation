"""
Global pytest configuration and environment isolation.

Ensures test runs default to fast, local, deterministic execution:
- GRAPH_BACKEND=local (uses SQLite prepared dataset)
- LLM_PROVIDER=none (uses deterministic templates, preventing external API calls)
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import pytest

from backend.config import settings

# The prepared SQLite graph store (174 MB) is runtime data, not source: it is
# gitignored and instead published as a GitHub Release asset. Sessions that
# declare PREPARED_DB_URL fetch it on demand; sessions without it simply run
# the store-independent tests (e.g. quick local unit runs).
PREPARED_DB_URL = os.environ.get("PREPARED_DB_URL", "")


def _ensure_prepared_db() -> None:
    target = Path(settings.prepared_db)
    if target.exists() or not PREPARED_DB_URL:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(PREPARED_DB_URL, timeout=600) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.replace(target)


@pytest.fixture(autouse=True, scope="session")
def prepared_dataset():
    """Materialize the prepared graph store before the session, when URL given."""
    _ensure_prepared_db()


@pytest.fixture(autouse=True, scope="session")
def isolate_test_environment():
    """Default test session to local graph store and disabled LLM calls.

    Also clears the Nebius Token Factory key so the full engine never makes
    live Nemotron calls from a test run; role tests provide their own mocks.
    """
    os.environ["GRAPH_BACKEND"] = "local"
    os.environ["LLM_PROVIDER"] = "none"
    os.environ["TG_HOST"] = ""
    os.environ["NEBIUS_API_KEY"] = ""
    settings.graph_backend = "local"
    settings.llm_provider = "none"
    settings.tg_host = ""
    settings.nebius_api_key = ""
