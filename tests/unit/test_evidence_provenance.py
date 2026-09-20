"""
Evidence provenance and uncertainty resolution tests.
"""
import pytest
from backend.risk.assessment import EvidenceSignals, build_risk_assessment
from backend.models import UncertaintyItem, RiskAssessment


class TestScoreBreakdown:
    def test_score_breakdown_not_empty(self):
        sig = EvidenceSignals(new_device=True, burst_online=2, customer_denied=True)
        ra = build_risk_assessment(sig)
        assert len(ra.score_breakdown) > 0

    def test_score_breakdown_has_total_entry(self):
        sig = EvidenceSignals(card_testing_sequence=True, small_online_count=4)
        ra = build_risk_assessment(sig)
        totals = [e for e in ra.score_breakdown if e.get("type") == "total"]
        assert len(totals) == 1

    def test_score_breakdown_fraud_signal_entries(self):
        sig = EvidenceSignals(new_device=True, customer_denied=True)
        ra = build_risk_assessment(sig)
        fraud_signals = [e for e in ra.score_breakdown if e.get("type") == "fraud_signal"]
        assert len(fraud_signals) >= 2

    def test_score_breakdown_clearing_signal_for_confirmed(self):
        sig = EvidenceSignals(customer_confirmed=True)
        ra = build_risk_assessment(sig)
        clearing = [e for e in ra.score_breakdown if e.get("type") == "clearing_signal"]
        assert any("customer_confirmed" in e["channel"] for e in clearing)

    def test_score_breakdown_entries_have_required_keys(self):
        sig = EvidenceSignals(new_device=True)
        ra = build_risk_assessment(sig)
        for entry in ra.score_breakdown:
            assert "channel" in entry
            assert "contribution" in entry
            assert "label" in entry
            assert "type" in entry

    def test_score_breakdown_total_matches_probability(self):
        sig = EvidenceSignals(new_device=True, burst_online=2)
        ra = build_risk_assessment(sig)
        totals = [e for e in ra.score_breakdown if e.get("type") == "total"]
        assert abs(totals[0]["contribution"] - ra.fraud_probability) < 0.001


class TestUncertaintyModel:
    def test_uncertainty_item_has_resolved_fields(self):
        """UncertaintyItem model should have resolved_by and resolution_impact."""
        item = UncertaintyItem(
            question="Did the cardholder make this?",
            impact="Denial raises probability",
            resolution_method="VERIFY_WITH_CUSTOMER",
        )
        assert hasattr(item, "resolved_by")
        assert hasattr(item, "resolution_impact")
        assert item.status == "open"

    def test_uncertainty_item_can_be_resolved(self):
        item = UncertaintyItem(
            question="Did the cardholder make this?",
            impact="Denial raises probability",
            resolution_method="VERIFY_WITH_CUSTOMER",
        )
        item.status = "resolved"
        item.resolved_by = "ER-abc123"
        item.resolution_impact = "Customer denial raised probability 0.43->0.76"
        assert item.status == "resolved"
        assert item.resolved_by == "ER-abc123"
        assert "0.43" in item.resolution_impact


class TestEvidenceProvenance:
    def test_ev_helper_populates_provenance(self):
        """The _ev helper should auto-populate provenance from ref string."""
        from backend.agents.orchestrator import _ev
        from backend.models import EvidenceSource, RiskLevel
        ev = _ev(
            "HHG-TEST",
            "Test claim",
            EvidenceSource.graph,
            "query:card_transaction_history(card_id=C123)",
            step=3,
        )
        assert ev.provenance is not None
        assert len(ev.provenance) > 0
        assert ev.provenance.get("step") == 3
        assert ev.provenance.get("claim_type") == "observed_fact"
        assert "card_transaction_history" in ev.provenance.get("query", "")

    def test_ev_helper_custom_claim_type(self):
        from backend.agents.orchestrator import _ev
        from backend.models import EvidenceSource
        ev = _ev(
            "HHG-TEST",
            "Risk score is 0.9",
            EvidenceSource.external,
            "model:risk_score",
            claim_type="model_score",
            step=1,
        )
        assert ev.provenance.get("claim_type") == "model_score"
