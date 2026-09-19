"""Unit tests for risk assessment and pattern detector."""
import pytest
from backend.risk.assessment import (
    EvidenceSignals, compute_fraud_probability, classify_risk,
    compute_confidence, build_risk_assessment, should_request_more_evidence,
)
from backend.risk.pattern_detector import detect_pattern
from backend.models import FraudPattern, RiskLevel


class TestFraudProbability:
    def test_low_base(self):
        sig = EvidenceSignals(trigger_risk_score=0.1, trigger_type="risk_score")
        prob = compute_fraud_probability(sig)
        assert 0.05 <= prob <= 0.15

    def test_card_testing_raises(self):
        sig = EvidenceSignals(card_testing_sequence=True, small_online_count=4)
        prob = compute_fraud_probability(sig)
        assert prob >= 0.35

    def test_customer_denied_raises(self):
        sig = EvidenceSignals(customer_denied=True)
        prob = compute_fraud_probability(sig)
        assert prob >= 0.30

    def test_customer_confirmed_lowers(self):
        sig = EvidenceSignals(
            trigger_risk_score=0.8, trigger_type="risk_score",
            customer_confirmed=True,
        )
        prob = compute_fraud_probability(sig)
        assert prob < 0.20

    def test_new_device_proxy_raises(self):
        sig = EvidenceSignals(new_device=True, proxy_used=True,
                              burst_online=3)
        prob = compute_fraud_probability(sig)
        assert prob >= 0.30

    def test_region_streak_lowers(self):
        sig = EvidenceSignals(new_region=True, region_streak=True)
        prob = compute_fraud_probability(sig)
        # Region streak dampens the new_region signal
        sig2 = EvidenceSignals(new_region=True, region_streak=False)
        prob2 = compute_fraud_probability(sig2)
        assert prob < prob2


class TestClassifyRisk:
    def test_critical(self):
        assert classify_risk(0.80) == RiskLevel.critical

    def test_low(self):
        assert classify_risk(0.10) == RiskLevel.low


class TestFullAssessment:
    def test_build_assessment(self):
        sig = EvidenceSignals(
            trigger_risk_score=0.6,
            trigger_type="risk_score",
            card_testing_sequence=True,
            small_online_count=3,
        )
        ra = build_risk_assessment(sig)
        assert ra.fraud_probability > 0.3
        assert len(ra.key_signals) > 0


class TestPatternDetector:
    def test_card_testing(self):
        sig = EvidenceSignals(card_testing_sequence=True, small_online_count=4)
        result = detect_pattern(sig)
        assert result.pattern == FraudPattern.card_testing
        assert result.confidence > 0.7

    def test_cnp_new_device(self):
        sig = EvidenceSignals(new_device=True, proxy_used=True, burst_online=2)
        result = detect_pattern(sig)
        assert result.pattern == FraudPattern.card_not_present_new_device

    def test_out_of_region(self):
        sig = EvidenceSignals(new_region=True, region_streak=False)
        result = detect_pattern(sig)
        assert result.pattern == FraudPattern.out_of_region_use

    def test_account_takeover(self):
        sig = EvidenceSignals(mixed_channel=True, match_flag_anomaly=True)
        result = detect_pattern(sig)
        assert result.pattern == FraudPattern.account_takeover

    def test_no_pattern(self):
        sig = EvidenceSignals()
        result = detect_pattern(sig)
        assert result.pattern == FraudPattern.none


class TestRequestMoreEvidence:
    def test_borderline_requests(self):
        sig = EvidenceSignals(independent_evidence_count=2)
        ra = build_risk_assessment(sig)
        ra.fraud_probability = 0.50
        from backend.models import UncertaintyItem
        ra.uncertainty_items = [UncertaintyItem(
            question="test?", impact="test", resolution_method="test"
        )]
        assert should_request_more_evidence(ra, sig, 0, 3) is True

    def test_at_limit_no_request(self):
        sig = EvidenceSignals()
        ra = build_risk_assessment(sig)
        assert should_request_more_evidence(ra, sig, 3, 3) is False
