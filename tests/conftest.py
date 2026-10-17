"""
Global pytest configuration and environment isolation.

Ensures test runs default to fast, local, deterministic execution:
- GRAPH_BACKEND=local (uses SQLite prepared dataset)
- LLM_PROVIDER=none (uses deterministic templates, preventing external API calls)
"""
from __future__ import annotations

import os
import pytest

from backend.config import settings


@pytest.fixture(autouse=True, scope="session")
def isolate_test_environment():
    """Default test session to local graph store and disabled LLM calls."""
    os.environ["GRAPH_BACKEND"] = "local"
    os.environ["LLM_PROVIDER"] = "none"
    settings.graph_backend = "local"
    settings.llm_provider = "none"
