"""
Integration tests for FastAPI backend endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
    def test_list_investigations(self, client):
        r = client.get("/investigations?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_get_investigation_existing(self, client):
        r = client.get("/investigations/HHG-001")
        assert r.status_code == 200
        data = r.json()
        assert data["case_id"] == "HHG-001"
        assert "case" in data
        assert "evidence_requests" in data
        assert "next_best_actions" in data

    def test_get_investigation_not_found(self, client):
        r = client.get("/investigations/NON_EXISTENT_CASE")
        assert r.status_code == 404

    def test_get_evidence(self, client):
        r = client.get("/investigations/HHG-001/evidence")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_timeline(self, client):
        r = client.get("/investigations/HHG-001/timeline")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_approvals(self, client):
        r = client.get("/investigations/HHG-001/approvals")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_create_investigation_idempotency(self, client):
        # Post with an idempotency key
        headers = {"Idempotency-Key": "test-key-api-001"}
        r1 = client.post("/investigations", json={"case_id": "HHG-001"}, headers=headers)
        assert r1.status_code == 200
        r2 = client.post("/investigations", json={"case_id": "HHG-001"}, headers=headers)
        assert r2.status_code == 200
        assert r1.json()["case_id"] == r2.json()["case_id"]


class TestGraphEndpoints:
    def test_get_graph_transaction(self, client):
        r = client.get("/graph/transaction/3514030")
        assert r.status_code == 200
        data = r.json()
        assert data["txn_id"] == "3514030"

    def test_get_customer_cards(self, client):
        r = client.get("/graph/customer/C12382/cards")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "C12382-K1" in data


class TestBenchmarkEndpoints:
    def test_get_benchmark_report(self, client):
        r = client.get("/benchmark/report")
        assert r.status_code == 200
        data = r.json()
        assert data["total_cases"] == 20
        assert data["completed"] == 20
        assert data["failed"] == 0
