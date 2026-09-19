"""
Integration checks for the LLM layer and the honesty flag.

The LLM is used only for text generation (summary, SAR narrative).  When no
provider is configured, output comes from deterministic grounded fallbacks and
case.llm_used must be False — template text is never presented as model output.
"""
from __future__ import annotations

import pytest

from backend.agents.orchestrator import _grounded_sar_narrative, _grounded_summary
from backend.config import settings
from backend.llm import client as llm
from backend.models import (
    Action, ActionRecommendation, ApprovalRoute, InvestigationCase, SARRecord,
    TriggerRecord, TriggerType,
)
from backend.risk.assessment import EvidenceSignals
from backend.models import Channel, TransactionRecord
from datetime import datetime


def _case():
    t = TriggerRecord(
        case_id="LLM-1", opened_at=datetime(2016, 11, 1),
        trigger_type=TriggerType.risk_score, trigger_text="scored 0.79",
        flagged_txn_id="3478782", card_id="C11891-K1", customer_id="C11891",
        risk_score=0.79,
    )
    return InvestigationCase(
        case_id="LLM-1", trigger=t, customer_id="C11891",
        card_id="C11891-K1", flagged_txn_id="3478782",
    )


class TestLLMHonestyFlag:
    def test_no_provider_returns_template_and_flag(self):
        settings.llm_provider = "none"
        text, tokens, used = llm.generate_summary("anything")
        assert used is False
        assert tokens == 0
        assert isinstance(text, str) and len(text) > 0

    def test_sar_no_provider_returns_template_and_flag(self):
        settings.llm_provider = "none"
        text, tokens, used = llm.generate_sar_narrative("anything")
        assert used is False
        assert tokens == 0

    def test_provider_available_flag(self, monkeypatch):
        settings.llm_provider = "anthropic"
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
        # Provider IS available, but the call must fail honestly and fall back
        monkeypatch.setattr(llm, "_call_anthropic",
                            lambda p: (_ for _ in ()).throw(RuntimeError("no network")))
        text, tokens, used = llm.generate_summary("prompt")
        assert used is False  # failed call is a fallback, not a success
        assert tokens == 0

    def test_provider_available_success(self, monkeypatch):
        settings.llm_provider = "anthropic"
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
        monkeypatch.setattr(llm, "_call_anthropic", lambda p: "LLM OUTPUT")
        text, tokens, used = llm.generate_summary("prompt text here")
        assert used is True
        assert text == "LLM OUTPUT"
        assert tokens > 0


class TestDeterministicFallbacks:
    def test_grounded_summary_uses_case_facts(self):
        case = _case()
        txn = TransactionRecord(
            txn_id="3478782", customer_id="C11891", card_id="C11891-K1",
            ts=datetime(2016, 11, 22), amount=292.36, product_cd="W",
            channel=Channel.online,
        )
        case.nba_final = [ActionRecommendation(
            action=Action.BLOCK_CARD, route=ApprovalRoute.L1, reason="R2")]
        sig = EvidenceSignals(evidence_count=5, independent_evidence_count=3)
        s = _grounded_summary(case, txn, sig)
        assert "LLM-1" in s
        assert "C11891-K1" in s
        assert "3478782" in s
        assert "292.36" in s
        assert "BLOCK_CARD" in s

    def test_grounded_sar_has_who_what_when_where(self):
        case = _case()
        case.sar = SARRecord(file=True, reason="R2: confirmed fraud")
        txn = TransactionRecord(
            txn_id="3478782", customer_id="C11891", card_id="C11891-K1",
            ts=datetime(2016, 11, 22), amount=292.36, product_cd="W",
            channel=Channel.online,
        )
        nar = _grounded_sar_narrative(case, txn, [txn], None)
        assert "C11891" in nar               # who
        assert "3478782" in nar              # what
        assert "2016-11-22" in nar           # when
        assert "online" in nar               # where/how
        assert "R2" in nar                   # why/policy
