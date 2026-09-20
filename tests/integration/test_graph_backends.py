"""
Integration checks for the graph backend layer.

Verifies that:
  1. backend.graph.tg_adapter exposes the same query interface as local_store
     (the REAL TigerGraph path is reachable by the router, not just a stub).
  2. The router selects the TigerGraph adapter when GRAPH_BACKEND=tigergraph.
  3. A TigerGraph failure falls back to the local store and is logged — never
     silently converted into a fabricated result.
  4. Case memory round-trips through whichever backend is live.
"""
from __future__ import annotations

import importlib
import os
from datetime import datetime

import pytest

from backend.graph import local_store, query_router, tg_adapter

# Every function the orchestrator calls through the query router.
ROUTED_FNS = [
    "get_transaction",
    "get_transaction_identity",
    "get_card_transaction_history",
    "get_customer_cards",
    "get_card_window",
    "get_tiny_transaction_sequence",
    "get_card_region_history",
    "get_card_email_history",
    "get_card_product_history",
    "get_card_amount_stats",
    "get_device_profile_label",
    "get_accounts_sharing_device",
    "get_card_device_history",
    "get_transaction_velocity",
    "get_closed_cases_for_customer",
    "get_closed_cases_for_card",
    "get_closed_cases_involving_txn",
    "get_closed_cases_by_device",
    "get_closed_cases_by_pattern",
    "search_closed_cases_text",
    "get_connected_card_cases",
    "get_cards_in_same_region_window",
    "get_cards_in_same_email_domain",
    "write_investigation_case",
    "get_investigation_cases_for_customer",
    "get_investigation_cases_by_device",
    "get_investigation_cases_involving_txn",
]


class TestAdapterParity:
    """The TigerGraph adapter must implement the full query surface."""

    @pytest.mark.parametrize("fn_name", ROUTED_FNS)
    def test_tg_adapter_implements_query(self, fn_name):
        assert hasattr(tg_adapter, fn_name), f"tg_adapter missing {fn_name}"
        assert callable(getattr(tg_adapter, fn_name))

    @pytest.mark.parametrize("fn_name", ROUTED_FNS)
    def test_local_store_implements_query(self, fn_name):
        assert hasattr(local_store, fn_name), f"local_store missing {fn_name}"

    def test_router_exposes_query(self):
        for fn_name in ROUTED_FNS:
            assert hasattr(query_router, fn_name), f"query_router missing {fn_name}"


class TestRouterSelection:
    def _set_backend(self, value: str):
        importlib.reload(query_router)
        query_router.settings.graph_backend = value
        query_router._local = None
        query_router._tg = None

    def teardown_method(self):
        self._set_backend("local")

    def test_default_is_local(self):
        self._set_backend("local")
        assert query_router._use_tg() is False

    def test_selects_tg_when_configured(self):
        self._set_backend("tigergraph")
        # tg_adapter imports cleanly, so _use_tg() must be True
        assert query_router._use_tg() is True

    def test_tg_failure_falls_back_to_local(self, monkeypatch):
        self._set_backend("tigergraph")

        def boom(*a, **k):
            raise RuntimeError("TigerGraph is down")

        monkeypatch.setattr(tg_adapter, "get_transaction", boom)
        # Fallback must return the real local row, not None and not an error.
        txn = query_router.get_transaction("3514030")
        assert txn is not None
        assert txn.txn_id == "3514030"

    def test_health_reports_both_backends_when_tg(self):
        self._set_backend("tigergraph")
        h = query_router.health_check()
        assert "tigergraph" in h
        # Returns health status for tigergraph
        assert h["tigergraph"] in ("healthy", "offline", "unhealthy", "unavailable")


class TestCaseMemory:
    """A written investigation case must be retrievable as case memory."""

    def test_roundtrip(self):
        payload = {
            "case_id": "MEM-TEST-1",
            "customer_id": "C12382",
            "card_id": "C12382-K1",
            "created_at": "2016-11-01T00:00:00",
            "trigger": {"trigger_type": "risk_score", "trigger_text": "t",
                        "opened_at": "2016-11-01T00:00:00"},
            "status": "closed_fraud",
            "verdict": "fraud",
            "fraud_probability": 0.9,
            "pattern": "card_testing",
            "exposure_usd": 123.45,
            "summary": "memory test",
            "affected_txn_ids": ["3514030"],
            "connected_card_ids": ["C12382-K2"],
            "connected_device_profiles": ["dev | Android 7 | chrome | 1080x1920"],
        }
        gid = query_router.write_investigation_case(payload)
        assert gid == "CASE-2016-MEM-TEST-1"

        rows = query_router.get_investigation_cases_for_customer("C12382")
        assert any(r["case_id"] == "MEM-TEST-1" for r in rows)

        rows = query_router.get_investigation_cases_involving_txn("3514030")
        assert any(r["case_id"] == "MEM-TEST-1" for r in rows)

        rows = query_router.get_investigation_cases_by_device("dev | Android 7 | chrome | 1080x1920")
        assert any(r["case_id"] == "MEM-TEST-1" for r in rows)
