"""
Integration checks for the policy → permission → approval → execution gate.

Requirement: no high-impact action bypasses its required approval.  The agent
recommends; only `auto` actions execute; L1/L2 actions become pending
ApprovalRequests and wait for a human.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.agents.orchestrator import _route_and_execute, run_investigation
from backend import db as app_db
from backend.models import (
    Action, ActionRecommendation, ApprovalRoute, EvidenceItem, EvidenceSource,
    InvestigationCase, TriggerRecord, TriggerType,
)
from backend.policies.engine import (
    can_auto_execute, get_route, should_file_sar, validate_action_permission,
)

HIGH_IMPACT = {
    Action.DECLINE_TRANSACTION, Action.BLOCK_CARD,
    Action.BLOCK_ALL_CARDS, Action.FILE_REPORT,
}


class TestPermissionGate:
    @pytest.mark.parametrize("action", list(Action))
    def test_route_matches_policy_table(self, action):
        route = get_route(action, exposure_usd=100.0)
        expected = {
            Action.DECLINE_TRANSACTION: ApprovalRoute.L1,
            Action.BLOCK_CARD: ApprovalRoute.L1,   # exposure <= 2500
            Action.BLOCK_ALL_CARDS: ApprovalRoute.L2,
            Action.FILE_REPORT: ApprovalRoute.L2,
        }.get(action, ApprovalRoute.auto)
        assert route == expected

    def test_block_card_escalates_to_l2_over_2500(self):
        assert get_route(Action.BLOCK_CARD, exposure_usd=2501) == ApprovalRoute.L2

    def test_only_auto_actions_execute(self):
        for action in Action:
            if can_auto_execute(action):
                assert get_route(action) == ApprovalRoute.auto
            else:
                assert action in HIGH_IMPACT

    def test_permission_validation_catches_wrong_route(self):
        ok, msg = validate_action_permission(Action.FILE_REPORT, ApprovalRoute.auto)
        assert ok is False
        assert "FILE_REPORT" in msg

    def test_permission_validation_accepts_correct_route(self):
        ok, _ = validate_action_permission(Action.FILE_REPORT, ApprovalRoute.L2)
        assert ok is True


def _case(case_id: str = "APR-1") -> InvestigationCase:
    t = TriggerRecord(
        case_id=case_id, opened_at=datetime(2016, 11, 1),
        trigger_type=TriggerType.risk_score, trigger_text="t",
        flagged_txn_id="3478782", card_id="C11891-K1", customer_id="C11891",
        risk_score=0.79,
    )
    case = InvestigationCase(
        case_id=case_id, trigger=t, customer_id="C11891",
        card_id="C11891-K1", flagged_txn_id="3478782",
        evidence=[EvidenceItem(case_id=case_id, claim="c", source=EvidenceSource.graph,
                               ref="q:test")],
    )
    # STEP 19 writes audit events and approvals, which are FK-bound to the
    # investigations row — persist the case exactly as the orchestrator does.
    app_db.save_investigation(case.case_id, case.state.value, case.model_dump(mode="json"))
    return case


class TestRoutingAndExecution:
    def test_auto_action_executes(self):
        case = _case()
        _route_and_execute(case, [ActionRecommendation(
            action=Action.MONITOR_CARD, route=ApprovalRoute.auto, reason="R4")])
        assert case.action_results[0].status == "executed"
        assert not case.approvals

    def test_high_impact_action_requires_approval(self):
        case = _case()
        _route_and_execute(case, [ActionRecommendation(
            action=Action.BLOCK_CARD, route=ApprovalRoute.L1, reason="R2")])
        assert case.approvals[0].status == "pending"
        assert case.approvals[0].required_route == ApprovalRoute.L1
        assert case.action_results[0].status == "pending_approval"
        # persisted so an approver can pick it up later
        loaded = app_db.load_approval(case.approvals[0].approval_id)
        assert loaded is not None

    def test_wrong_route_is_rejected_not_executed(self):
        case = _case()
        _route_and_execute(case, [ActionRecommendation(
            action=Action.FILE_REPORT, route=ApprovalRoute.auto, reason="R6")])
        assert case.action_results[0].status == "failed"
        assert not case.approvals

    def test_blocked_all_cards_never_auto(self):
        case = _case()
        _route_and_execute(case, [ActionRecommendation(
            action=Action.BLOCK_ALL_CARDS, route=ApprovalRoute.L2, reason="R10")])
        assert case.action_results[0].status == "pending_approval"

    def test_mixed_actions_route_correctly(self):
        case = _case()
        _route_and_execute(case, [
            ActionRecommendation(action=Action.CREATE_CASE, route=ApprovalRoute.auto, reason="R2"),
            ActionRecommendation(action=Action.BLOCK_CARD, route=ApprovalRoute.L1, reason="R2"),
            ActionRecommendation(action=Action.FILE_REPORT, route=ApprovalRoute.L2, reason="R2"),
        ])
        statuses = {r.action: r.status for r in case.action_results}
        assert statuses[Action.CREATE_CASE] == "executed"
        assert statuses[Action.BLOCK_CARD] == "pending_approval"
        assert statuses[Action.FILE_REPORT] == "pending_approval"

    def test_end_to_end_case_has_audit_trail(self):
        case = run_investigation("HHG-003", force=True)
        trail = app_db.get_audit_trail(case.case_id)
        events = {e["event_type"] for e in trail}
        assert "case_created" in events
        assert "state_transition" in events
        assert "case_written_to_graph" in events
        # every non-auto final action must have an approval record
        for rec in case.nba_final:
            if not can_auto_execute(rec.action):
                assert any(a.action == rec.action and a.status == "pending"
                           for a in case.approvals), \
                    f"{rec.action} missing approval record"


class TestSARConsistency:
    def test_sar_agrees_with_file_report(self):
        case = _case()
        actions = [ActionRecommendation(
            action=Action.FILE_REPORT, route=ApprovalRoute.L2, reason="R2")]
        file_, reason = should_file_sar(actions, 2000.0, True, verdict="fraud")
        assert file_ is True and reason.startswith("R2")

    def test_no_file_report_means_no_sar(self):
        file_, _ = should_file_sar([], 5000.0, True, verdict="fraud")
        assert file_ is False
