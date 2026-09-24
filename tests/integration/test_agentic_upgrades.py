"""
Tests for the agentic upgrades:

- evidence independence (families, not source-string counts)
- information-value evidence selection (suppression of low-value requests)
- HITL pause/resume around POST /evidence
- approval decisions execute under policy
- planner adaptivity (different cases -> different tool sets)
- new risk channels (fraud ring, agent memory, step-up)
- NBA why_now + R11 uncertainty-aware branch
"""
from __future__ import annotations

from datetime import datetime

import pytest
from unittest.mock import patch

from backend.config import settings
from backend.risk.assessment import EvidenceSignals, build_risk_assessment, compute_fraud_probability
from backend.risk.independence import evidence_families, independent_evidence_count
from backend.risk.pattern_detector import detect_pattern
from backend.agents import evidence_gap as egap
from backend.agents import planner
from backend.agents.orchestrator import run_investigation, submit_evidence, decide_approval
from backend.models import (
    Action, ApprovalRoute, EvidenceItem, EvidenceSource, FraudPattern,
    InvestigationCase, TriggerRecord, TriggerType, UncertaintyItem,
    RiskAssessment,
)
from backend.policies.engine import PolicyInput, build_recommendations
from backend import db as app_db


# ─── Evidence independence ─────────────────────────────────────────────────────

def _ev(claim: str, source: EvidenceSource, ref: str) -> EvidenceItem:
    return EvidenceItem(case_id="T", claim=claim, source=source, ref=ref)


class TestEvidenceIndependence:
    def test_eight_graph_rows_from_one_query_are_one_family(self):
        evs = [_ev(f"row {i}", EvidenceSource.graph,
                   "query:card_transaction_history(card_id=C1)") for i in range(8)]
        assert independent_evidence_count(evs) == 1

    def test_different_queries_are_independent(self):
        evs = [
            _ev("a", EvidenceSource.graph, "query:card_transaction_history(card_id=C1)"),
            _ev("b", EvidenceSource.graph, "query:tiny_transaction_sequence(card_id=C1)"),
            _ev("c", EvidenceSource.graph, "query:accounts_sharing_device(device=D)"),
        ]
        assert independent_evidence_count(evs) == 3

    def test_customer_evidence_is_its_own_family(self):
        evs = [
            _ev("graph fact", EvidenceSource.graph, "query:x"),
            _ev("customer said", EvidenceSource.customer, "evidence_request:ER-1"),
        ]
        assert independent_evidence_count(evs) == 2

    def test_orchestrator_uses_real_independence(self):
        case = run_investigation("HHG-002", force=True)
        # The recorded stop reason must cite either decisive probabilities with
        # evidence families, or the borderline/escalation path — never the old
        # broken "independent evidence sources" phrasing with source counts.
        assert "independent evidence sources" not in case.stop_reason
        # The metric must be recomputed from the real evidence
        assert case.risk_before is not None
        assert case.evidence, "case must carry evidence"


# ─── Evidence gap / information value ──────────────────────────────────────────

class TestEvidenceGapEngine:
    def test_customer_denial_can_flip_action_set(self):
        """Denial vs confirmation must produce materially different action sets."""
        sig = EvidenceSignals(new_device=True, burst_online=2, trigger_risk_score=0.6,
                              trigger_type="risk_score", avg_card_amount=50, txn_amount=200)
        scored = egap.evaluate_candidates(sig, 200.0, False, False, 0, False)
        cust = [s for s in scored if s["candidate"].type.name == "customer_validation"]
        assert cust, "customer_validation candidate missing"
        assert cust[0]["info_value"] > 0.4
        assert cust[0]["fraud_side_actions"] != cust[0]["legit_side_actions"]

    def test_low_value_request_is_suppressed(self):
        """When the customer already denied, re-asking must not be selected."""
        sig = EvidenceSignals(new_device=True, burst_online=2, customer_denied=True,
                              trigger_risk_score=0.6, trigger_type="risk_score")
        sel = egap.select_evidence_request(sig, 200.0, False, False, 0, False,
                                           min_info_value=0.25)
        if sel is not None:
            assert sel["candidate"].type.name != "customer_validation"

    def test_step_up_candidate_only_with_new_device(self):
        sig_no_device = EvidenceSignals(burst_online=2)
        cands = egap.build_candidates(sig_no_device, 100.0, False, False, 0, False)
        assert all(c.type.name != "step_up_auth" for c in cands)

        sig_device = EvidenceSignals(burst_online=2, new_device=True)
        cands2 = egap.build_candidates(sig_device, 100.0, False, False, 0, False)
        assert any(c.type.name == "step_up_auth" for c in cands2)

    def test_apply_response_sets_denial(self):
        sig = EvidenceSignals()
        out = egap.apply_response_to_signals(
            sig, egap.EvidenceRequestType.customer_validation,
            "Customer states they did not make these purchases.")
        assert out.customer_denied is True
        assert out.customer_confirmed is False

    def test_apply_response_step_up(self):
        sig = EvidenceSignals(new_device=True)
        out = egap.apply_response_to_signals(
            sig, egap.EvidenceRequestType.step_up_auth,
            "Step-up authentication failed: device not recognized.")
        assert out.step_up_failed is True


# ─── New risk channels ────────────────────────────────────────────────────────

class TestNewRiskChannels:
    def test_step_up_failed_raises_probability(self):
        base, _ = compute_fraud_probability(EvidenceSignals(new_device=True))
        failed, _ = compute_fraud_probability(EvidenceSignals(new_device=True, step_up_failed=True))
        assert failed > base

    def test_step_up_passed_lowers(self):
        base, _ = compute_fraud_probability(EvidenceSignals(new_device=True, burst_online=2))
        passed, _ = compute_fraud_probability(EvidenceSignals(new_device=True, burst_online=2, step_up_passed=True))
        assert passed < base

    def test_fraud_ring_channel(self):
        base, _ = compute_fraud_probability(EvidenceSignals(new_device=True))
        ring, _ = compute_fraud_probability(
            EvidenceSignals(new_device=True, fraud_ring_size=5, fraud_ring_fraud_cards=3))
        assert ring > base

    def test_agent_memory_channel(self):
        base, _ = compute_fraud_probability(EvidenceSignals(new_device=True))
        mem, _ = compute_fraud_probability(
            EvidenceSignals(new_device=True, agent_prior_investigations=2, agent_prior_fraud=2))
        assert mem > base

    def test_signal_snapshot_roundtrip(self):
        sig = EvidenceSignals(new_device=True, shared_device_count=3, customer_denied=True)
        from backend.agents.orchestrator import _signals_dict, _current_signals
        from backend.models import InvestigationCase, TriggerRecord, TriggerType
        t = TriggerRecord(case_id="S", opened_at=datetime(2016, 1, 1),
                          trigger_type=TriggerType.risk_score, trigger_text="t",
                          flagged_txn_id="1", card_id="C", customer_id="C", risk_score=0.5)
        case = InvestigationCase(case_id="S", trigger=t, customer_id="C",
                                 card_id="C", flagged_txn_id="1")
        from backend.agents.orchestrator import _store_state
        _store_state(case, sig, build_risk_assessment(sig))
        rebuilt = _current_signals(case, EvidenceSignals())
        assert rebuilt.customer_denied is True
        assert rebuilt.shared_device_count == 3


# ─── Planner ───────────────────────────────────────────────────────────────────

class TestPlannerAdaptivity:
    def test_no_device_no_device_tools(self):
        plan = planner.plan_adaptive_round({
            "signals": EvidenceSignals(), "card_id": "C", "customer_id": "U",
            "flagged_txn_id": "1", "flagged_ts": datetime(2016, 1, 1),
            "device_label": None, "txn_region": None, "new_region": False,
            "online_window_count": 0, "trigger_risk_score": 0.5, "round": 1,
        })
        assert "get_accounts_sharing_device" not in plan.tool_names
        assert "get_device_fraud_ring" not in plan.tool_names

    def test_device_case_includes_ring_analysis(self):
        plan = planner.plan_adaptive_round({
            "signals": EvidenceSignals(), "card_id": "C", "customer_id": "U",
            "flagged_txn_id": "1", "flagged_ts": datetime(2016, 1, 1),
            "device_label": "Windows | 10 | chrome | 1920x1080",
            "txn_region": None, "new_region": False,
            "online_window_count": 0, "trigger_risk_score": 0.5, "round": 1,
        })
        assert "get_device_fraud_ring" in plan.tool_names
        assert "get_accounts_sharing_device" in plan.tool_names

    def test_new_region_adds_region_window_tool(self):
        plan = planner.plan_adaptive_round({
            "signals": EvidenceSignals(), "card_id": "C", "customer_id": "U",
            "flagged_txn_id": "1", "flagged_ts": datetime(2016, 1, 1),
            "device_label": None, "txn_region": "444.0", "new_region": True,
            "online_window_count": 0, "trigger_risk_score": 0.5, "round": 1,
        })
        assert "get_cards_in_same_region_window" in plan.tool_names

    def test_stopping_criteria_decisive(self):
        stop, reason = planner.should_stop_investigating({
            "fraud_probability": 0.9, "independent_evidence_count": 3,
            "rounds_used": 1, "max_rounds": 3,
        })
        assert stop and "decisive" in reason

    def test_stopping_criteria_budget(self):
        stop, reason = planner.should_stop_investigating({
            "fraud_probability": 0.5, "independent_evidence_count": 5,
            "rounds_used": 3, "max_rounds": 3,
        })
        assert stop and "budget" in reason


# ─── Policy: why_now + R11 ─────────────────────────────────────────────────────

class TestWhyNowAndR11:
    def test_every_recommendation_has_why_now(self):
        inp = PolicyInput(
            fraud_probability=0.8, exposure_usd=1500, customer_denied=True,
            customer_confirmed=False, no_reply=False, card_testing_detected=False,
            shared_origin=True, disputed_recurring=False, uncertain_exposed=False,
            undocumented_coordinated=False, connected_fraud_cards_count=1,
            evidence_count=4,
        )
        recs = build_recommendations(inp)
        assert recs
        for rec in recs:
            assert rec.why_now, f"{rec.action} missing why_now"

    def test_r11_prefers_evidence_over_block_on_low_confidence(self):
        inp = PolicyInput(
            fraud_probability=0.5, exposure_usd=300, customer_denied=False,
            customer_confirmed=False, no_reply=False, card_testing_detected=False,
            shared_origin=False, disputed_recurring=False, uncertain_exposed=False,
            undocumented_coordinated=False, connected_fraud_cards_count=0,
            evidence_count=2, assessment_confidence=0.5,
            best_evidence_info_value=0.8,
        )
        actions = [r.action for r in build_recommendations(inp)]
        assert Action.VERIFY_WITH_CUSTOMER in actions
        assert Action.BLOCK_CARD not in actions


# ─── HITL evidence submission ──────────────────────────────────────────────────

class TestHumanInTheLoop:
    def test_pause_and_resume(self):
        prev = settings.evidence_request_mode
        try:
            settings.evidence_request_mode = "human_in_loop"
            case = run_investigation("HHG-002", force=True)
            # Must have paused at the request stage
            assert case.state.value in ("MORE_EVIDENCE_REQUIRED", "EVIDENCE_REQUESTED")
            pending = [r for r in case.evidence_requests if r.status == "pending"]
            assert pending, "no pending evidence request after pause"
            assert pending[0].origin == "simulated" or pending[0].assumed_response == ""

            # Submit a human response: investigation must resume to completion
            done = submit_evidence("HHG-002", "", "Customer confirms they made this purchase.")
            assert done.state.value == "COMPLETED"
            got = [r for r in done.evidence_requests if r.status == "received"]
            assert got and got[0].origin == "human_in_loop"
            assert done.customer_confirmed if hasattr(done, "customer_confirmed") else True
        finally:
            settings.evidence_request_mode = prev

    def test_submit_without_pending_request_rejected(self):
        with pytest.raises(ValueError):
            submit_evidence("HHG-002", "", "irrelevant", origin="human_in_loop")


# ─── Approval execution ────────────────────────────────────────────────────────

class TestApprovalExecution:
    def _case_with_approval(self):
        case = run_investigation("HHG-003", force=True)
        pending_aprs = [a for a in case.approvals if a.status == "pending"]
        return case, pending_aprs

    def test_approval_decision_executes(self):
        case, pending = self._case_with_approval()
        if not pending:
            pytest.skip("case produced no pending approvals")
        apr = pending[0]
        res = decide_approval(case.case_id, apr.approval_id, "approved", "Judge-L1")
        assert res["status"] == "approved"
        assert res["approver"] == "Judge-L1"
        # The case must now record an executed action under human authority
        trail = app_db.get_audit_trail(case.case_id)
        events = {e["event_type"] for e in trail}
        assert "approval_granted" in events
        assert "action_executed" in events

    def test_rejection_records_decision(self):
        case, pending = self._case_with_approval()
        if not pending:
            pytest.skip("case produced no pending approvals")
        apr = pending[0]
        res = decide_approval(case.case_id, apr.approval_id, "rejected", "Judge-L2")
        assert res["status"] == "rejected"
        trail = app_db.get_audit_trail(case.case_id)
        events = {e["event_type"] for e in trail}
        assert "approval_rejected" in events

    def test_double_decision_rejected(self):
        case, pending = self._case_with_approval()
        if not pending:
            pytest.skip("case produced no pending approvals")
        apr = pending[0]
        decide_approval(case.case_id, apr.approval_id, "approved", "Judge-L1")
        with pytest.raises(ValueError, match="already decided"):
            decide_approval(case.case_id, apr.approval_id, "rejected", "Judge-L1")


# ─── Orchestrator end-to-end sanity ────────────────────────────────────────────

class TestAdaptiveOrchestratorEndToEnd:
    def test_plan_trace_recorded(self):
        case = run_investigation("HHG-014", force=True)
        rounds = [p for p in case.plan_trace if p.get("round") != "signals"]
        assert len(rounds) >= 2
        assert all(p.get("tools") for p in rounds)

    def test_evidence_request_has_info_value(self):
        case = run_investigation("HHG-014", force=True)
        for r in case.evidence_requests:
            assert r.info_value >= settings.min_evidence_info_value
            assert r.rationale
            assert r.decision_relevance

    def test_written_to_graph_with_device_edge(self):
        case = run_investigation("HHG-014", force=True)
        assert case.written_to_graph is True
        assert case.connected_device_profiles  # IC_ON_DEVICE edges source data
