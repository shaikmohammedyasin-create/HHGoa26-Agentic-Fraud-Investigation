"""Unit tests for the policy engine."""
import pytest
from backend.policies.engine import (
    PolicyInput, build_recommendations, get_route, should_file_sar,
    can_auto_execute, validate_action_permission,
)
from backend.models import Action, ApprovalRoute


def _inp(**overrides):
    defaults = dict(
        fraud_probability=0.5,
        exposure_usd=200.0,
        customer_denied=False,
        customer_confirmed=False,
        no_reply=False,
        card_testing_detected=False,
        shared_origin=False,
        disputed_recurring=False,
        uncertain_exposed=False,
        undocumented_coordinated=False,
        connected_fraud_cards_count=0,
        evidence_count=3,
    )
    defaults.update(overrides)
    return PolicyInput(**defaults)


class TestApprovalRouting:
    def test_auto_actions(self):
        for a in [Action.ALLOW_TRANSACTION, Action.MONITOR_CARD, Action.CLOSE_NO_FRAUD,
                   Action.CREATE_CASE, Action.ESCALATE_TO_ANALYST]:
            assert get_route(a) == ApprovalRoute.auto

    def test_decline_is_L1(self):
        assert get_route(Action.DECLINE_TRANSACTION) == ApprovalRoute.L1

    def test_block_card_L1_under_2500(self):
        assert get_route(Action.BLOCK_CARD, exposure_usd=2000) == ApprovalRoute.L1

    def test_block_card_L2_over_2500(self):
        assert get_route(Action.BLOCK_CARD, exposure_usd=3000) == ApprovalRoute.L2

    def test_file_report_L2(self):
        assert get_route(Action.FILE_REPORT) == ApprovalRoute.L2

    def test_block_all_cards_L2(self):
        assert get_route(Action.BLOCK_ALL_CARDS) == ApprovalRoute.L2


class TestR1SingleSignal:
    def test_verify_before_block(self):
        inp = _inp(fraud_probability=0.55, evidence_count=1)
        actions = build_recommendations(inp)
        action_names = {a.action for a in actions}
        assert Action.VERIFY_WITH_CUSTOMER in action_names
        assert Action.BLOCK_CARD not in action_names


class TestR2CustomerDenied:
    def test_block_and_case(self):
        inp = _inp(customer_denied=True, fraud_probability=0.7)
        actions = build_recommendations(inp)
        names = {a.action for a in actions}
        assert Action.BLOCK_CARD in names
        assert Action.CREATE_CASE in names

    def test_file_report_high_exposure(self):
        inp = _inp(customer_denied=True, exposure_usd=1500)
        actions = build_recommendations(inp)
        names = {a.action for a in actions}
        assert Action.FILE_REPORT in names


class TestR3CustomerConfirmed:
    def test_close_no_fraud(self):
        inp = _inp(customer_confirmed=True, fraud_probability=0.3)
        actions = build_recommendations(inp)
        names = {a.action for a in actions}
        assert Action.CLOSE_NO_FRAUD in names


class TestR5CardTesting:
    def test_decline_step_up(self):
        inp = _inp(card_testing_detected=True, exposure_usd=50)
        actions = build_recommendations(inp)
        names = {a.action for a in actions}
        assert Action.DECLINE_TRANSACTION in names
        assert Action.STEP_UP_AUTH in names

    def test_block_over_100(self):
        inp = _inp(card_testing_detected=True, exposure_usd=150)
        actions = build_recommendations(inp)
        names = {a.action for a in actions}
        assert Action.BLOCK_CARD in names


class TestSARFiling:
    def test_no_sar_when_legitimate(self):
        from backend.models import ActionRecommendation
        actions = [ActionRecommendation(action=Action.CLOSE_NO_FRAUD,
                                        route=ApprovalRoute.auto, reason="test")]
        file, reason = should_file_sar(actions, 0, False, "legitimate")
        assert file is False

    def test_sar_when_fraud_and_file_report(self):
        from backend.models import ActionRecommendation
        actions = [ActionRecommendation(action=Action.FILE_REPORT,
                                        route=ApprovalRoute.L2, reason="R2")]
        file, reason = should_file_sar(actions, 2000, False, "fraud")
        assert file is True


class TestAutoExecute:
    def test_allow_is_auto(self):
        assert can_auto_execute(Action.ALLOW_TRANSACTION) is True

    def test_block_is_not_auto(self):
        assert can_auto_execute(Action.BLOCK_CARD) is False
