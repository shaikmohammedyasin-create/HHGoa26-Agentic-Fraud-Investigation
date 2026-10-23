"""
Integration tests for FastAPI backend endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.graph import query_router as graph
from backend.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestSystemEndpoints:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("healthy", "degraded")
        assert "graph" in data
        assert "app_db" in data
        assert "llm_provider" in data


class TestInvestigationEndpoints:
    @pytest.fixture(autouse=True, scope="class")
    @classmethod
    def setup_class(cls):
        from backend.agents.orchestrator import run_investigation
        run_investigation("CASE-001", force=False)

    def test_list_investigations(self, client):
        r = client.get("/investigations?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_investigation_existing(self, client):
        r = client.get("/investigations/CASE-001")
        assert r.status_code == 200
        data = r.json()
        assert data["case_id"] == "CASE-001"
        assert "case" in data
        assert "evidence_requests" in data
        assert "next_best_actions" in data

    def test_get_investigation_not_found(self, client):
        r = client.get("/investigations/NON_EXISTENT_CASE")
        assert r.status_code == 404

    def test_get_evidence(self, client):
        r = client.get("/investigations/CASE-001/evidence")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_timeline(self, client):
        r = client.get("/investigations/CASE-001/timeline")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_approvals(self, client):
        r = client.get("/investigations/CASE-001/approvals")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_create_investigation_idempotency(self, client):
        # Post with an idempotency key
        headers = {"Idempotency-Key": "test-key-api-001"}
        r1 = client.post("/investigations", json={"case_id": "CASE-001"}, headers=headers)
        assert r1.status_code == 200
        r2 = client.post("/investigations", json={"case_id": "CASE-001"}, headers=headers)
        assert r2.status_code == 200
        assert r1.json()["case_id"] == r2.json()["case_id"]


class TestGraphEndpoints:
    def test_get_graph_transaction(self, client):
        trigger = graph.get_case_trigger("CASE-006")
        assert trigger is not None
        txn_id = trigger["flagged_txn_id"]
        r = client.get(f"/graph/transaction/{txn_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["txn_id"] == txn_id

    def test_get_customer_cards(self, client):
        trigger = graph.get_case_trigger("CASE-006")
        customer_id = trigger["customer_id"]
        r = client.get(f"/graph/customer/{customer_id}/cards")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert trigger["card_id"] in data


class TestBenchmarkEndpoints:
    def test_get_benchmark_report(self, client):
        r = client.get("/benchmark/report")
        assert r.status_code == 200
        data = r.json()
        assert data["total_cases"] == 20
        assert data["completed"] == 20
        assert data["failed"] == 0
