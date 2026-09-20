# -*- coding: utf-8 -*-
import pytest
from backend.risk.assessment import EvidenceSignals
from backend.risk.pattern_detector import detect_pattern
from backend.models import FraudPattern

class TestMultiCandidateScoring:
    def test_two_co_present_patterns_returns_secondary(self):
        sig = EvidenceSignals(new_device=True, burst_online=2)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_new_device
        assert r.secondary == FraudPattern.card_not_present_fraud

    def test_candidates_list_not_empty(self):
        sig = EvidenceSignals(new_device=True, burst_online=2)
        r = detect_pattern(sig)
        assert len(r.candidates) >= 2

    def test_candidates_sorted_by_score(self):
        sig = EvidenceSignals(new_device=True, burst_online=3)
        r = detect_pattern(sig)
        scores = [c.score for c in r.candidates]
        assert scores == sorted(scores, reverse=True)

class TestTiebreaker1:
    def test_new_device_only_prefers_cnp_new_device(self):
        sig = EvidenceSignals(new_device=True, burst_online=1)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_new_device
        assert r.pattern != FraudPattern.account_takeover

    def test_mixed_channel_prefers_ato(self):
        sig = EvidenceSignals(mixed_channel=True, match_flag_anomaly=True)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.account_takeover

    def test_new_device_with_mixed_channel_allows_ato(self):
        sig = EvidenceSignals(new_device=True, mixed_channel=True, match_flag_anomaly=True)
        r = detect_pattern(sig)
        ato_in_result = (r.pattern == FraudPattern.account_takeover or r.secondary == FraudPattern.account_takeover)
        assert ato_in_result

class TestTiebreaker2:
    def test_new_device_true_prefers_cnp_new_device(self):
        sig = EvidenceSignals(new_device=True, burst_online=2)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_new_device

    def test_no_new_device_does_not_prefer_cnp_new_device(self):
        sig = EvidenceSignals(burst_online=3, new_device=False)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_fraud

class TestCardTestingDominance:
    def test_card_testing_dominates(self):
        sig = EvidenceSignals(card_testing_sequence=True, small_online_count=4, new_device=True, mixed_channel=True)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_testing
        assert r.confidence > 0.85

class TestRegionStreak:
    def test_region_streak_suppresses_out_of_region(self):
        sig = EvidenceSignals(new_region=True, region_streak=True)
        r = detect_pattern(sig)
        assert r.pattern != FraudPattern.out_of_region_use

    def test_new_region_without_streak_produces_out_of_region(self):
        sig = EvidenceSignals(new_region=True, region_streak=False)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.out_of_region_use

class TestInsufficientEvidence:
    def test_no_signals_returns_none(self):
        sig = EvidenceSignals()
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.none
        assert r.insufficient_evidence is True

    def test_undocumented_coordinated(self):
        sig = EvidenceSignals(device_linked_fraud=2, evidence_count=5, shared_device_count=3)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.undocumented

class TestSupportingSignals:
    def test_supporting_signals_populated(self):
        sig = EvidenceSignals(new_device=True, burst_online=2)
        r = detect_pattern(sig)
        assert len(r.candidates[0].supporting_signals) > 0

    def test_contradicting_signals_for_demoted_ato(self):
        sig = EvidenceSignals(new_device=True, burst_online=1)
        r = detect_pattern(sig)
        ato_candidates = [c for c in r.candidates if c.pattern == FraudPattern.account_takeover]
        if ato_candidates:
            assert len(ato_candidates[0].contradicting_signals) > 0


class TestTargetedPatternReasoningHardening:
    """
    Generalized tests mandated by Step 9 covering evidence-grounded pattern reasoning.
    Uses purely synthetic EvidenceSignals. Never references case IDs.
    """

    def test_scenario_a_new_device_mixed_channel_no_anomaly(self):
        """A. new_device=True, mixed_channel=True, match_flag_anomaly=False -> CNP-new-device outranks ATO."""
        sig = EvidenceSignals(new_device=True, mixed_channel=True, match_flag_anomaly=False, burst_online=1)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_new_device
        cand_patterns = [c.pattern for c in r.candidates]
        assert FraudPattern.card_not_present_new_device in cand_patterns
        if FraudPattern.account_takeover in cand_patterns:
            nd_score = next(c.score for c in r.candidates if c.pattern == FraudPattern.card_not_present_new_device)
            ato_score = next(c.score for c in r.candidates if c.pattern == FraudPattern.account_takeover)
            assert nd_score > ato_score

    def test_scenario_b_new_device_mixed_channel_with_anomaly(self):
        """B. new_device=True, mixed_channel=True, match_flag_anomaly=True -> ATO remains a serious/high candidate."""
        sig = EvidenceSignals(new_device=True, mixed_channel=True, match_flag_anomaly=True, burst_online=1)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.account_takeover
        cand_patterns = [c.pattern for c in r.candidates]
        assert FraudPattern.account_takeover in cand_patterns

    def test_scenario_c_no_new_device_mixed_channel_with_anomaly(self):
        """C. new_device=False, mixed_channel=True, match_flag_anomaly=True -> ATO can be primary."""
        sig = EvidenceSignals(new_device=False, mixed_channel=True, match_flag_anomaly=True)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.account_takeover

    def test_scenario_d_tiny_online_authorizations_followed_by_purchase(self):
        """D. three tiny online transactions + larger transaction -> card_testing strongly detected."""
        sig = EvidenceSignals(card_testing_sequence=True, small_online_count=3, txn_amount=150.0, avg_card_amount=40.0)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_testing
        assert r.confidence >= 0.85

    def test_scenario_e_online_burst_unusual_amount_no_new_device(self):
        """E. online burst + unusual amount without new device -> card_not_present_fraud candidate/primary."""
        sig = EvidenceSignals(burst_online=3, txn_amount=250.0, avg_card_amount=50.0, new_device=False)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_fraud
        assert FraudPattern.card_not_present_fraud in [c.pattern for c in r.candidates]

    def test_scenario_f_new_device_online_no_other_evidence(self):
        """F. new device + online transaction + no other evidence -> CNP-new-device candidate, not ATO by default."""
        sig = EvidenceSignals(new_device=True, burst_online=1, mixed_channel=False, match_flag_anomaly=False)
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.card_not_present_new_device
        cand_patterns = [c.pattern for c in r.candidates]
        assert FraudPattern.account_takeover not in cand_patterns or r.pattern != FraudPattern.account_takeover

    def test_scenario_g_coordinated_cross_account_undocumented(self):
        """G. no known pattern but genuine coordinated cross-account evidence -> undocumented."""
        sig = EvidenceSignals(
            new_device=False,
            mixed_channel=False,
            card_testing_sequence=False,
            new_region=False,
            burst_online=0,
            evidence_count=4,
            shared_device_count=3,
            device_linked_fraud=2,
        )
        r = detect_pattern(sig)
        assert r.pattern == FraudPattern.undocumented

