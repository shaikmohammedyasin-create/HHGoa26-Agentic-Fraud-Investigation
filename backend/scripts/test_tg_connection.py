"""
TigerGraph Connectivity & Authentication Verifier.

Tests:
1. Hostname DNS resolution
2. Unauthenticated /echo endpoint
3. Authenticated /graphs endpoint
4. Existence of target graph (fraud_investigation)

Usage:
    python -m backend.scripts.test_tg_connection
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings
from backend.graph.tg_adapter import _tg_base_url


from scripts.test_tigergraph_connection import run_connection_test


def test_connection():
    return run_connection_test()


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
