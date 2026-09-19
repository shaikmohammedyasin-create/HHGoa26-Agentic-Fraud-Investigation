"""
Integration tests for Analyst Command Center Frontend & API endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend import db as app_db
from backend.agents.orchestrator import run_investigation


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestFrontendAPI:
    def test_get_cases_listing(self, client):
        """GET /api/cases must return the official 20 benchmark case triggers."""
        r = client.get("/api/cases")
        assert r.status_code == 200
        cases = r.json()
        assert isinstance(cases, list)
        assert len(cases) == 20
        first = cases[0]
        assert "case_id" in first
        assert "trigger_type" in first
        assert "flagged_txn_id" in first
        assert "card_id" in first
        assert "customer_id" in first

    def test_get_full_investigation_existing(self, client):
        """GET /api/investigations/{case_id}/full must return rich internal case model."""
        # Ensure HHG-001 is investigated
        run_investigation("HHG-001", force=False)
        r = client.get("/api/investigations/HHG-001/full")
        assert r.status_code == 200
        data = r.json()
        assert data["case_id"] == "HHG-001"
        assert "verdict" in data
        assert "fraud_probability" in data
        assert "pattern" in data
        assert "uncertainty" in data
        assert "evidence_requests" in data
        assert "approvals" in data
        assert "sar" in data
        assert "written_to_graph" in data

    def test_get_full_investigation_not_found(self, client):
        """GET /api/investigations/{case_id}/full must return 404 for non-existent case."""
        r = client.get("/api/investigations/NON_EXISTENT_CASE_123/full")
        assert r.status_code == 404

    def test_get_investigation_graph_structure(self, client):
        """GET /api/investigations/{case_id}/graph must return valid node-link subgraph."""
        r = client.get("/api/investigations/HHG-001/graph")
        assert r.status_code == 200
        graph_data = r.json()
        assert "nodes" in graph_data
        assert "links" in graph_data
        assert len(graph_data["nodes"]) >= 3  # At least Customer, Card, FlaggedTxn
        node_types = {n["type"] for n in graph_data["nodes"]}
        assert "Customer" in node_types
        assert "Card" in node_types
        assert "FlaggedTransaction" in node_types

    def test_investigation_timeline_and_evidence(self, client):
        """GET /investigations/{case_id}/timeline and /evidence must return valid lists."""
        r_ev = client.get("/investigations/HHG-001/evidence")
        assert r_ev.status_code == 200
        evidence = r_ev.json()
        assert isinstance(evidence, list)
        assert len(evidence) >= 1

        r_time = client.get("/investigations/HHG-001/timeline")
        assert r_time.status_code == 200
        timeline = r_time.json()
        assert isinstance(timeline, list)
        assert len(timeline) >= 1

    def test_approval_decision_workflow(self, client):
        """POST /investigations/{case_id}/approvals/{approval_id} must update decision."""
        # Create an approval if none exists
        approvals = app_db.list_pending_approvals("HHG-001")
        if not approvals:
            from backend.models import ApprovalRequest, Action, ApprovalRoute
            apr = ApprovalRequest(
                case_id="HHG-001",
                action=Action.block_card,
                reason="Test approval",
                required_route=ApprovalRoute.L1,
            )
            app_db.save_approval(apr.approval_id, "HHG-001", apr.model_dump(mode="json"))
            approval_id = apr.approval_id
        else:
            approval_id = approvals[0]["approval_id"]

        # Approve
        r = client.post(
            f"/investigations/HHG-001/approvals/{approval_id}",
            json={"decision": "approved", "approver": "TestAnalyst-L1"}
        )
        assert r.status_code == 200
        res = r.json()
        assert res["status"] == "approved"
        assert res["approver"] == "TestAnalyst-L1"

    def test_static_frontend_mount(self, client):
        """Root and static assets must be accessible."""
        r_root = client.get("/")
        assert r_root.status_code == 200
        assert "HHGoa" in r_root.text

        r_css = client.get("/css/style.css")
        assert r_css.status_code == 200

        r_api = client.get("/js/api.js")
        assert r_api.status_code == 200

        r_graph = client.get("/js/graph.js")
        assert r_graph.status_code == 200

        r_app = client.get("/js/app.js")
        assert r_app.status_code == 200
