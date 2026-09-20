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
