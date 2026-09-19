"""
Phase B Hardening: Failure tests and adversarial checks.
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime
from unittest.mock import patch

from backend.config import settings
from backend.models import (
    TriggerRecord, TriggerType, InvestigationCase, InvestigationState,
    ApprovalRoute, Action
)
from backend.agents.orchestrator import run_investigation
from backend.graph import query_router
from backend.mcp.client import MCPClient, MCPUnavailableError
from backend.policies.engine import get_route, can_auto_execute
from backend import db as app_db


class TestFailureScenarios:
    def test_mcp_unavailable_fails_closed(self):
        """MCP unavailable must fail closed or raise MCPUnavailableError, never fabricate data."""
        client = MCPClient(base_url="http://127.0.0.1:9")
        with pytest.raises(MCPUnavailableError):
            client.call_tool("run_query", {"query_name": "test"})

    def test_unknown_transaction_handling(self):
        """Investigation of a non-existent transaction must transition to failed state gracefully."""
        mock_trigger = {
            "case_id": "FAIL-TXN-001",
            "opened_at": "2016-12-05T00:00:00",
            "trigger_type": "risk_score",
            "trigger_text": "Test unknown txn",
            "flagged_txn_id": "99999999_NON_EXISTENT",
            "card_id": "C99999-K1",
            "customer_id": "C99999",
            "risk_score": 0.85,
        }
        with patch("backend.agents.orchestrator.graph.get_case_trigger", return_value=mock_trigger):
            res = run_investigation("FAIL-TXN-001", force=True)
            assert res.state == InvestigationState.failed
            assert "not found in graph" in res.stop_reason

    def test_unknown_card_returns_empty_gracefully(self):
        """Card queries for an unknown card must return empty list without throwing."""
        res = query_router.get_card_transaction_history("CARD_DOES_NOT_EXIST_9999")
        assert isinstance(res, list)
        assert len(res) == 0

    def test_insufficient_evidence_escalates_and_monitors(self):
        """When evidence is insufficient/borderline, policy must not block card; requires review."""
        res = run_investigation("HHG-001", force=True)
        action_names = [a.action for a in res.nba_final]
        assert Action.BLOCK_ALL_CARDS not in action_names
        assert res.verdict.value == "uncertain"

    def test_malformed_trigger_handling(self):
        """Missing or unknown case trigger must raise ValueError."""
        with pytest.raises(ValueError, match="not found in case_pack"):
            run_investigation("INVALID_TRIGGER_ID_999", force=True)

    def test_llm_unavailable_uses_deterministic_fallback(self):
        """When LLM provider is unavailable, fallback deterministic summary is generated."""
        with patch.object(settings, "llm_provider", "none"):
            res = run_investigation("HHG-001", force=True)
            assert res.llm_used is False
            assert len(res.summary) > 20
            assert "C12382" in res.summary

    def test_tigergraph_unavailable_in_strict_mode(self):
        """In strict mode, TigerGraph failures must raise RuntimeError rather than silently falling back."""
        with patch.object(settings, "strict_graph_backend", True):
            with patch.object(settings, "graph_backend", "tigergraph"):
                with patch("backend.graph.tg_adapter.get_transaction", side_effect=Exception("Connection refused")):
                    with pytest.raises(RuntimeError, match="TigerGraph execution failed in strict mode"):
                        query_router.get_transaction("3514030")


class TestLifecycleAndProvenance:
    def test_case_lifecycle_creation_and_update(self):
        """Verify case vertex can be created and updated in graph memory."""
        res = run_investigation("HHG-001", force=True)
        assert res.written_to_graph is True
        assert res.graph_case_id.startswith("CASE-")

        # Verify audit trail in app_db contains creation and graph persistence events
        trail = app_db.get_audit_trail("HHG-001")
        event_types = [e["event_type"] for e in trail]
        assert "case_created_in_graph" in event_types
        assert "case_written_to_graph" in event_types

    def test_evidence_provenance_integrity(self):
        """Every evidence claim must have a valid non-empty source and reference."""
        res = run_investigation("HHG-001", force=True)
        for ev in res.evidence:
            assert ev.source is not None
            assert len(ev.claim) > 0
            assert len(ev.ref) > 0
            assert ":" in ev.ref  # e.g., query:... or retrieval:... or trigger:...

    def test_policy_engine_separation(self):
        """Actions are partitioned into auto vs L1 vs L2, independent of LLM."""
        assert get_route(Action.CREATE_CASE) == ApprovalRoute.auto
        assert get_route(Action.DECLINE_TRANSACTION) == ApprovalRoute.L1
        assert get_route(Action.BLOCK_CARD) in (ApprovalRoute.L1, ApprovalRoute.L2)
        assert get_route(Action.BLOCK_ALL_CARDS) == ApprovalRoute.L2
        assert get_route(Action.FILE_REPORT) == ApprovalRoute.L2
        assert can_auto_execute(Action.BLOCK_CARD) is False
