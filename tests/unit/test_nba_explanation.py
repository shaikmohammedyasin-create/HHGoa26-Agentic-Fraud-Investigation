"""
Generalisation tests for the NBA explanation engine.

Verifies that ActionRecommendation now carries evidence_ids,
alternatives_rejected, and expected_impact per recommendation.
"""
import pytest
from backend.policies.engine import (
    PolicyInput, build_recommendations, get_route, can_auto_execute,
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
        evidence_ids=["EV-001", "EV-002", "EV-003"],
    )
    defaults.update(overrides)
    return PolicyInput(**defaults)


class TestExplanationFields:
    def test_block_card_has_evidence_ids(self):
        inp = _inp(customer_denied=True, fraud_probability=0.8)
        actions = build_recommendations(inp)
        block = next(a for a in actions if a.action == Action.BLOCK_CARD)
        assert len(block.evidence_ids) > 0

    def test_block_card_lists_monitor_as_rejected(self):
        inp = _inp(customer_denied=True, fraud_probability=0.8)
        actions = build_recommendations(inp)
        block = next(a for a in actions if a.action == Action.BLOCK_CARD)
        rejected_text = " ".join(block.alternatives_rejected)
        assert "MONITOR_CARD" in rejected_text

    def test_block_card_has_expected_impact(self):
        inp = _inp(customer_denied=True, fraud_probability=0.8)
        actions = build_recommendations(inp)
        block = next(a for a in actions if a.action == Action.BLOCK_CARD)
        assert len(block.expected_impact) > 0

    def test_close_no_fraud_lists_block_as_rejected(self):
        inp = _inp(customer_confirmed=True, fraud_probability=0.2)
        actions = build_recommendations(inp)
        close = next(a for a in actions if a.action == Action.CLOSE_NO_FRAUD)
        rejected_text = " ".join(close.alternatives_rejected)
        assert "BLOCK_CARD" in rejected_text

    def test_allow_transaction_lists_block_as_rejected(self):
        inp = _inp(fraud_probability=0.05, evidence_count=0)
        actions = build_recommendations(inp)
        allow = next(a for a in actions if a.action == Action.ALLOW_TRANSACTION)
        rejected_text = " ".join(allow.alternatives_rejected)
        assert "BLOCK_CARD" in rejected_text

    def test_verify_customer_r1_lists_block_as_rejected(self):
        inp = _inp(fraud_probability=0.55, evidence_count=1)
        actions = build_recommendations(inp)
        verify = next(a for a in actions if a.action == Action.VERIFY_WITH_CUSTOMER)
        rejected_text = " ".join(verify.alternatives_rejected)
        assert "BLOCK_CARD" in rejected_text


class TestPolicyConstraints:
    def test_block_all_cards_absent_when_insufficient_fraud_cards(self):
        """R10: BLOCK_ALL_CARDS must not appear when connected_fraud_cards_count < 2."""
        inp = _inp(fraud_probability=0.9, connected_fraud_cards_count=1)
        actions = build_recommendations(inp)
        assert Action.BLOCK_ALL_CARDS not in {a.action for a in actions}

    def test_file_report_is_not_auto(self):
        assert can_auto_execute(Action.FILE_REPORT) is False

    def test_l1_routing_boundary(self):
        """BLOCK_CARD under $2,500 -> L1; over $2,500 -> L2."""
        assert get_route(Action.BLOCK_CARD, 2000.0) == ApprovalRoute.L1
        assert get_route(Action.BLOCK_CARD, 3000.0) == ApprovalRoute.L2

    def test_card_testing_step_up_has_expected_impact(self):
        inp = _inp(card_testing_detected=True, exposure_usd=50)
        actions = build_recommendations(inp)
        step_up = next(a for a in actions if a.action == Action.STEP_UP_AUTH)
        assert len(step_up.expected_impact) > 0
