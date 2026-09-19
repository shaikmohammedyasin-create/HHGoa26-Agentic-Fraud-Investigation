"""
Pydantic v2 data contracts.

These are the internal rich models.  The answer-file schema (README Answer Format)
is a strict subset exported by backend.evaluation.exporter.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class TriggerType(str, Enum):
    risk_score = "risk_score"
    customer_report = "customer_report"
    analyst_request = "analyst_request"


class Channel(str, Enum):
    online = "online"
    in_person = "in_person"


class FraudPattern(str, Enum):
    card_testing = "card_testing"
    card_not_present_fraud = "card_not_present_fraud"
    card_not_present_new_device = "card_not_present_new_device"
    out_of_region_use = "out_of_region_use"
    account_takeover = "account_takeover"
    undocumented = "undocumented"
    none = "none"


class CaseStatus(str, Enum):
    open = "open"
    closed_fraud = "closed_fraud"
    closed_legitimate = "closed_legitimate"
    escalated = "escalated"


class Verdict(str, Enum):
    fraud = "fraud"
    legitimate = "legitimate"
    uncertain = "uncertain"


class InvestigationState(str, Enum):
    triggered = "TRIGGERED"
    case_created = "CASE_CREATED"
    investigating = "INVESTIGATING"
    evidence_gathered = "EVIDENCE_GATHERED"
    assessing = "ASSESSING"
    more_evidence_required = "MORE_EVIDENCE_REQUIRED"
    evidence_requested = "EVIDENCE_REQUESTED"
    evidence_received = "EVIDENCE_RECEIVED"
    reassessing = "REASSESSING"
    action_recommended = "ACTION_RECOMMENDED"
    approval_required = "APPROVAL_REQUIRED"
    action_approved = "ACTION_APPROVED"
    action_executing = "ACTION_EXECUTING"
    action_executed = "ACTION_EXECUTED"
    completed = "COMPLETED"
    failed = "FAILED"
    escalated = "ESCALATED"
    blocked = "BLOCKED"
    cancelled = "CANCELLED"


class RiskLevel(str, Enum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"
    critical = "CRITICAL"


class ApprovalRoute(str, Enum):
    auto = "auto"
    L1 = "L1"
    L2 = "L2"


class Action(str, Enum):
    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class EvidenceSource(str, Enum):
    graph = "graph"
    document = "document"
    customer = "customer"
    external = "external"


class EvidenceRequestType(str, Enum):
    customer_validation = "customer_validation"
    step_up_auth = "step_up_auth"
    analyst_info = "analyst_info"


# ─────────────────────────────────────────────────────────────────────────────
# Fundamental records
# ─────────────────────────────────────────────────────────────────────────────

class TriggerRecord(BaseModel):
    case_id: str
    opened_at: datetime
    trigger_type: TriggerType
    trigger_text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    risk_score: float | None = None


class TransactionRecord(BaseModel):
    txn_id: str
    customer_id: str
    card_id: str
    ts: datetime
    amount: float
    product_cd: str
    channel: Channel
    addr1: str | None = None
    addr2: str | None = None
    p_email: str | None = None
    r_email: str | None = None
    risk_score: float | None = None
    # Key Vesta signals (not the full 339)
    c1: float | None = None   # count of addresses on card
    d1: float | None = None   # days since last txn
    m4: str | None = None     # match flag
    has_identity: bool = False


class IdentityRecord(BaseModel):
    txn_id: str
    device_type: str | None = None
    device_info: str | None = None
    os: str | None = None           # id_30
    browser: str | None = None      # id_31
    screen: str | None = None       # id_33
    device_status: str | None = None  # id_15:  New | Found | NotFound
    proxy: str | None = None          # id_23
    match_status: str | None = None   # id_34


class DeviceProfileKey(BaseModel):
    """Canonical device profile string used as vertex key."""
    device_info: str
    os: str
    browser: str
    screen: str

    def label(self) -> str:
        parts = [
            self.device_info or "unknown",
            self.os or "unknown",
            self.browser or "unknown",
            self.screen or "unknown",
        ]
        return " | ".join(p.strip() for p in parts)


class HistoricalCase(BaseModel):
    case_id: str
    customer_id: str
    card_id: str
    opened_at: datetime
    closed_at: datetime
    outcome: str                             # confirmed_fraud | cleared
    pattern: str
    first_fraud_txn_id: str | None = None
    txn_ids: list[str] = Field(default_factory=list)
    n_txns: int = 0
    exposure_usd: float = 0.0
    connected_card_ids: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    report_filed: bool = False
    analyst_notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Evidence
# ─────────────────────────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"EV-{uuid4().hex[:8]}")
    case_id: str
    claim: str
    source: EvidenceSource
    ref: str                             # query name, doc section, request id
    entity_ids: list[str] = Field(default_factory=list)
    severity: RiskLevel = RiskLevel.medium
    confidence: float = 0.5             # 0-1 how certain this piece of evidence is
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    provenance: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Uncertainty
# ─────────────────────────────────────────────────────────────────────────────

class UncertaintyItem(BaseModel):
    question: str
    impact: str        # what changes if resolved
    resolution_method: str
    status: str = "open"   # open | resolved | waived


# ─────────────────────────────────────────────────────────────────────────────
# Evidence request / additional evidence workflow
# ─────────────────────────────────────────────────────────────────────────────

class EvidenceRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"ER-{uuid4().hex[:8]}")
    case_id: str
    type: EvidenceRequestType
    asked_after_step: int
    rationale: str           # why needed
    question: str            # what is being asked
    assumed_response: str = ""
    status: str = "pending"  # pending | received | waived
    received_at: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Risk / confidence assessment
# ─────────────────────────────────────────────────────────────────────────────

class RiskAssessment(BaseModel):
    fraud_probability: float
    risk_level: RiskLevel
    confidence: float            # in the probability estimate
    key_signals: list[str] = Field(default_factory=list)
    uncertainty_items: list[UncertaintyItem] = Field(default_factory=list)
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Actions / next-best-action
# ─────────────────────────────────────────────────────────────────────────────

class ActionRecommendation(BaseModel):
    action: Action
    route: ApprovalRoute
    reason: str              # cite the policy rule


class NextBestActions(BaseModel):
    initial: list[ActionRecommendation] = Field(default_factory=list)
    final: list[ActionRecommendation] = Field(default_factory=list)
    what_changed: str = "nothing"


# ─────────────────────────────────────────────────────────────────────────────
# SAR
# ─────────────────────────────────────────────────────────────────────────────

class SARRecord(BaseModel):
    file: bool = False
    reason: str = ""
    narrative: str = ""
    subjects: list[str] = Field(default_factory=list)
    total_amount_usd: float = 0.0
    activity_dates: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Approval
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"APR-{uuid4().hex[:8]}")
    case_id: str
    action: Action
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ref: str = ""
    required_route: ApprovalRoute
    status: str = "pending"    # pending | approved | rejected
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: datetime | None = None
    approver: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Action execution result
# ─────────────────────────────────────────────────────────────────────────────

class ActionResult(BaseModel):
    action: Action
    status: str    # executed | skipped | pending_approval | failed
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    result: str = ""
    case_id: str = ""
    approval_ref: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Investigation case (internal full record)
# ─────────────────────────────────────────────────────────────────────────────

class InvestigationCase(BaseModel):
    # Identity
    case_id: str
    trigger: TriggerRecord
    state: InvestigationState = InvestigationState.triggered
    step: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Subject
    customer_id: str
    card_id: str
    flagged_txn_id: str

    # Findings
    status: CaseStatus = CaseStatus.open
    verdict: Verdict = Verdict.uncertain
    fraud_probability: float = 0.0
    risk_level: RiskLevel = RiskLevel.low
    pattern: FraudPattern = FraudPattern.none
    pattern_description: str = ""
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)
    exposure_usd: float = 0.0

    # Evidence
    evidence: list[EvidenceItem] = Field(default_factory=list)
    uncertainty: list[UncertaintyItem] = Field(default_factory=list)
    similar_prior_cases: list[str] = Field(default_factory=list)

    # Evidence workflow
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)

    # Next-best-action (before/after)
    risk_before: RiskAssessment | None = None
    nba_initial: list[ActionRecommendation] = Field(default_factory=list)
    nba_final: list[ActionRecommendation] = Field(default_factory=list)
    nba_what_changed: str = "nothing"

    # SAR
    sar: SARRecord = Field(default_factory=SARRecord)

    # Graph persistence
    written_to_graph: bool = False
    graph_case_id: str = ""

    # Action execution / approval (internal; exported through the audit trail)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    action_results: list[ActionResult] = Field(default_factory=list)

    # Capability provenance (internal: keeps real vs fallback paths visible)
    graph_backend: str = "local"
    mcp_status: str = "not_configured"   # ok | unavailable | not_configured
    llm_used: bool = False

    # Metadata
    summary: str = ""
    stop_reason: str = ""
    tool_calls: int = 0
    tokens_used: int = 0
    latency_s: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Audit event
# ─────────────────────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"AE-{uuid4().hex[:8]}")
    case_id: str
    event_type: str
    state_from: str | None = None
    state_to: str | None = None
    actor: str = "agent"
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
