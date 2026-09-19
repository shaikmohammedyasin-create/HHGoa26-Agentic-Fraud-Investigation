"""
Integration tests for the live TigerGraph adapter and failure resilience.
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime

from backend.config import settings
from backend.graph import query_router, tg_adapter
from backend.mcp.client import MCPClient, MCPUnavailableError
from backend.agents.orchestrator import run_investigation


class TestTigerGraphLiveAdapter:
    @pytest.fixture(autouse=True)
    def setup_tg(self):
        # Only run if TigerGraph host is configured
        if not settings.tg_host:
            pytest.skip("TigerGraph host not configured")

    def test_amount_stats_format(self):
        stats = tg_adapter.get_card_amount_stats("C07297-K1")
        assert isinstance(stats, dict)
        if stats:
            assert "avg_amt" in stats
            assert "n" in stats
            assert stats["n"] > 0

    def test_region_history_format(self):
        regions = tg_adapter.get_card_region_history("C07297-K1")
        assert isinstance(regions, list)
        if regions:
            assert "addr1" in regions[0]
            assert len(regions[0]["addr1"]) > 0

    def test_device_profile_label_resolution(self):
        label = tg_adapter.get_device_profile_label("3476682")
        assert label is not None
        assert "Windows" in label or "Trident" in label or "unknown" in label

    def test_device_neighbors_deployed_and_callable(self):
        """Regression test: device_neighbors query is deployed, callable, and returns expected accounts."""
        # Test with known device in live graph
        results = tg_adapter.get_accounts_sharing_device("iOS Device | iOS 9.3.5 | mobile safari 9.0 | 1024x768")
        assert isinstance(results, list)
        for row in results:
            assert "card_id" in row
            assert "customer_id" in row

        # Test unknown device returns empty list gracefully
        unknown = tg_adapter.get_accounts_sharing_device("NON_EXISTENT_DEVICE_XYZ")
        assert isinstance(unknown, list)
        assert len(unknown) == 0

    def test_cases_by_device_deployed_and_callable(self):
        """Regression test: cases_by_device query is deployed, callable, and returns matching closed cases."""
        cases = tg_adapter.get_closed_cases_by_device("Windows")
        assert isinstance(cases, list)
        assert len(cases) > 0
        for c in cases:
            assert hasattr(c, "case_id") and c.case_id
            assert hasattr(c, "pattern") and c.pattern

    def test_strict_mode_device_neighbors_does_not_fail_closed(self):
        """Strict mode live graph call to device_neighbors succeeds with no HTTP 404."""
        prev_strict = settings.strict_graph_backend
        prev_backend = settings.graph_backend
        try:
            settings.strict_graph_backend = True
            settings.graph_backend = "tigergraph"
            results = query_router.get_accounts_sharing_device("iOS Device | iOS 9.3.5 | mobile safari 9.0 | 1024x768")
            assert isinstance(results, list)
        finally:
            settings.strict_graph_backend = prev_strict
            settings.graph_backend = prev_backend


class TestFailureHandling:
    def test_unknown_transaction_returns_none(self):
        txn = query_router.get_transaction("9999999999_NON_EXISTENT")
        assert txn is None

    def test_unknown_card_history_returns_empty(self):
        history = query_router.get_card_transaction_history("NON_EXISTENT_CARD_9999")
        assert isinstance(history, list)
        assert len(history) == 0

    def test_unknown_customer_cards_returns_empty(self):
        cards = query_router.get_customer_cards("NON_EXISTENT_CUSTOMER_9999")
        assert isinstance(cards, list)
        assert len(cards) == 0

    def test_mcp_unreachable_server_fails_closed(self):
        c = MCPClient(base_url="http://127.0.0.1:9")
        with pytest.raises(MCPUnavailableError):
            c.call_tool("run_query", {"query_name": "card_window"})
