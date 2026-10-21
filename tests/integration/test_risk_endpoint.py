"""
Integration tests for the explainable risk analysis endpoint
GET /api/investigations/{case_id}/risk (TRACER integration work).

Every value surfaced by this endpoint must originate from the real risk
engine or the persisted investigation / audit trail — the tests below pin
those guarantees so the UI can never be fed fabricated numbers.
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


class TestRiskAnalysisEndpoint:
    def test_risk_analysis_existing_case(self, client):
        """The endpoint returns a validated engine-derived risk decomposition."""
        run_investigation("CASE-001", force=False)
        r = client.get("/api/investigations/CASE-001/risk")
        assert r.status_code == 200
        data = r.json()

        assert data["case_id"] == "CASE-001"

        # Current assessment comes from the deterministic engine rebuild.
        current = data["current"]
        assert 0.0 <= current["fraud_probability"] <= 1.0
        assert current["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

        # Score breakdown is real engine output: fraud/clearing channels plus
        # a total row whose contribution equals the posterior probability.
        breakdown = current["score_breakdown"]
        assert len(breakdown) >= 1
        types = {ch["type"] for ch in breakdown}
        assert types <= {"fraud_signal", "clearing_signal", "total"}
        total_rows = [ch for ch in breakdown if ch["type"] == "total"]
        assert total_rows
        assert abs(total_rows[0]["contribution"] - current["fraud_probability"]) < 0.01
        # Every channel row carries a human-readable label (auditability).
        for ch in breakdown:
            assert ch["label"], "channel label must not be empty"
            assert "channel" in ch and "contribution" in ch

    def test_risk_analysis_trajectory_is_real_data_only(self, client):
        """Trajectory points all originate from real engine assessments."""
        r = client.get("/api/investigations/CASE-001/risk")
        assert r.status_code == 200
        data = r.json()

        traj = data["trajectory"]
        assert len(traj) >= 1
        assert [pt["step"] for pt in traj] == list(range(len(traj)))
        for pt in traj:
            assert pt["origin"] in {"bank_model", "graph_evidence", "evidence_response"}
            assert 0.0 <= pt["probability"] <= 1.0
            assert pt["label"]
        # The first point, if present, is the bank trigger model score.
        if data["prior"]:
            assert traj[0]["origin"] == "bank_model"
            assert traj[0]["probability"] == pytest.approx(data["prior"]["bank_risk_score"], abs=1e-4)
        # The final trajectory point equals the current posterior probability.
        current = data["current"]["fraud_probability"]
        assert abs(traj[-1]["probability"] - current) < 1e-3

    def test_risk_analysis_evidence_type_counts_mirror_payload(self, client):
        """Evidence provenance counts must match the stored investigation."""
        payload = app_db.load_investigation("CASE-001")
        r = client.get("/api/investigations/CASE-001/risk")
        assert r.status_code == 200
        data = r.json()

        counts = data["evidence_type_counts"]
        expected_total = len(payload.get("evidence", []))
        assert counts["total"] == expected_total
        assert (
            counts["observed_fact"] + counts["derived_inference"] + counts["model_score"]
            == expected_total
        )

    def test_risk_analysis_not_found(self, client):
        """Unknown cases must 404 rather than fabricate an analysis."""
        r = client.get("/api/investigations/NON_EXISTENT_CASE_XYZ/risk")
        assert r.status_code == 404

    def test_risk_analysis_matches_headline_probability(self, client):
        """The rebuilt posterior must match the stored headline probability."""
        payload = app_db.load_investigation("CASE-001")
        r = client.get("/api/investigations/CASE-001/risk")
        data = r.json()
        assert data["current"]["fraud_probability"] == pytest.approx(
            payload["fraud_probability"], abs=0.01
        )
