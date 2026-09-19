"""Unit tests for backend.models – contract validation."""
import pytest
from backend.models import (
    InvestigationCase, TriggerRecord, TriggerType, InvestigationState,
    CaseStatus, Verdict, FraudPattern, EvidenceItem, EvidenceSource,
    ActionRecommendation, Action, ApprovalRoute, SARRecord, RiskLevel,
    AuditEvent,
)
from datetime import datetime


def _trigger(**overrides):
    defaults = dict(
        case_id="HHG-T01",
        opened_at=datetime(2016, 12, 1),
        trigger_type=TriggerType.risk_score,
        trigger_text="test trigger",
        flagged_txn_id="3500001",
        card_id="C00001-K1",
        customer_id="C00001",
        risk_score=0.6,
    )
    defaults.update(overrides)
    return TriggerRecord(**defaults)


def test_trigger_record_happy():
    t = _trigger()
    assert t.case_id == "HHG-T01"
    assert t.risk_score == 0.6


def test_investigation_case_defaults():
    t = _trigger()
    case = InvestigationCase(
        case_id="HHG-T01",
        trigger=t,
        customer_id=t.customer_id,
        card_id=t.card_id,
        flagged_txn_id=t.flagged_txn_id,
    )
    assert case.state == InvestigationState.triggered
    assert case.verdict == Verdict.uncertain
    assert case.pattern == FraudPattern.none
    assert case.evidence == []
    assert case.exposure_usd == 0.0


def test_evidence_item_id_generated():
    ev = EvidenceItem(case_id="X", claim="test", source=EvidenceSource.graph, ref="q:test")
    assert ev.evidence_id.startswith("EV-")


def test_action_recommendation():
    ar = ActionRecommendation(
        action=Action.BLOCK_CARD,
        route=ApprovalRoute.L1,
        reason="R2",
    )
    assert ar.action == Action.BLOCK_CARD


def test_sar_record_no_file():
    sar = SARRecord()
    assert sar.file is False
    assert sar.narrative == ""
    assert sar.subjects == []


def test_audit_event_id():
    ae = AuditEvent(case_id="X", event_type="test")
    assert ae.event_id.startswith("AE-")
