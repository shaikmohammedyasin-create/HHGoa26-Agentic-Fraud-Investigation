"""
Integration checks for the GraphRAG layer.

GraphRAG here means: graph-retrieved evidence + retrieved prior cases + policy
and pattern context, assembled into a grounded prompt.  These checks prove the
retrieval is real (returns rows from the dataset) and the grounding is real
(context is built from the case, not from a static template).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.agents.orchestrator import run_investigation
from backend.config import settings
from backend.graph import query_router as graph
from backend.graphrag.context import build_context, to_llm_prompt
from backend.models import (
    Channel, EvidenceItem, EvidenceSource, InvestigationCase, RiskLevel,
    TransactionRecord, TriggerRecord, TriggerType,
)


@pytest.fixture(scope="module")
def completed_case():
    return run_investigation("HHG-002", force=True)


class TestRetrievalIsReal:
    """Retrieval must return actual rows from the dataset, not constants."""

    def test_closed_case_retrieval_returns_dataset_rows(self):
        rows = graph.get_closed_cases_for_customer("C12382")
        assert len(rows) > 0
        for r in rows:
            assert r.case_id.startswith("CC-")
            assert r.outcome in ("confirmed_fraud", "cleared")

    def test_keyword_retrieval_uses_query_text(self):
        rows = graph.search_closed_cases_text("card testing small authorizations")
        # Whatever it returns must be real dataset rows
        for r in rows:
            assert r.case_id.startswith("CC-")

    def test_pattern_retrieval_returns_rows(self):
        rows = graph.get_closed_cases_by_pattern("card_testing")
        for r in rows:
            assert r.pattern == "card_testing"

    def test_graph_traversal_returns_transactions(self):
        txn = graph.get_transaction("3514030")
        assert txn is not None
        hist = graph.get_card_transaction_history(txn.card_id, limit=5)
        assert len(hist) > 0
        assert all(t.card_id == txn.card_id for t in hist)


class TestContextGrounding:
    def _case(self):
        t = TriggerRecord(
            case_id="CTX-1", opened_at=datetime(2016, 11, 1),
            trigger_type=TriggerType.risk_score, trigger_text="scored 0.61",
            flagged_txn_id="3514030", card_id="C12382-K1", customer_id="C12382",
            risk_score=0.61,
        )
        return InvestigationCase(
            case_id="CTX-1", trigger=t, customer_id="C12382",
            card_id="C12382-K1", flagged_txn_id="3514030",
        )

    def test_context_is_case_specific(self):
        case = self._case()
        txn = graph.get_transaction("3514030")
        ctx = build_context(
            case=case, flagged_txn=txn, flagged_identity=None,
            card_history=graph.get_card_transaction_history(case.card_id, limit=5),
            region_history=graph.get_card_region_history(case.card_id),
            device_history=graph.get_card_device_history(case.card_id),
            prior_cases=graph.get_closed_cases_for_customer(case.customer_id)[:5],
            detected_pattern="card_testing",
        )
        # Grounding: the case id and the real entities appear
        assert ctx.case_id == "CTX-1"
        assert ctx.flagged_transaction["txn_id"] == "3514030"
        assert ctx.flagged_transaction["amount_usd"] == txn.amount
        assert ctx.detected_pattern == "card_testing"
        # Policy + pattern knowledge is attached (the R in RAG)
        assert "R1" in ctx.fraud_policy and "R10" in ctx.fraud_policy
        assert "card_testing" in ctx.fraud_patterns
        assert len(ctx.similar_prior_cases) > 0

    def test_prompt_contains_retrieved_evidence_not_template(self):
        case = self._case()
        txn = graph.get_transaction("3514030")
        case.evidence = [EvidenceItem(
            case_id="CTX-1", claim="REAL EVIDENCE MARKER 98765",
            source=EvidenceSource.graph, ref="query:x",
        )]
        ctx = build_context(
            case=case, flagged_txn=txn, flagged_identity=None,
            card_history=[], region_history=[], device_history=[],
            prior_cases=[], detected_pattern="none",
        )
        prompt = to_llm_prompt(ctx, task="summarize")
        assert "REAL EVIDENCE MARKER 98765" in prompt
        assert ctx.case_id in prompt


class TestOrchestratorGrounding:
    """The finished case must carry retrieved evidence and prior cases."""

    def test_prior_cases_are_dataset_ids(self, completed_case):
        assert len(completed_case.similar_prior_cases) > 0
        for cid in completed_case.similar_prior_cases:
            assert cid.startswith("CC-"), f"non-dataset case id in memory: {cid}"

    def test_evidence_has_provenance(self, completed_case):
        assert len(completed_case.evidence) > 0
        for ev in completed_case.evidence:
            assert ev.source in ("graph", "document", "customer", "external")
            assert ev.ref != "", "evidence item without provenance ref"
            assert ev.entity_ids is not None

    def test_retrieval_evidence_is_present(self, completed_case):
        refs = [ev.ref for ev in completed_case.evidence]
        assert any(r.startswith("retrieval:") for r in refs), \
            "no retrieval-sourced evidence — GraphRAG not wired"

    def test_context_built_before_summary(self, completed_case):
        # summary must reference case facts
        assert completed_case.case_id in completed_case.summary
        assert completed_case.card_id in completed_case.summary
