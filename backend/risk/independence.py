"""
Evidence independence model.

Fixes the broken "independent evidence" metric: previously independence was
`len({source strings})`, which counted eight graph queries as ONE independent
source while counting one graph fact + one LLM-generated document as two.

The correct notion for a fraud decision: evidence items are independent when
they come from different *underlying signals* — different vertices, queries and
provenance paths — not different labels.  We therefore cluster evidence into
families by (source, provenance query/ref path).  Items in the same family are
treated as manifestations of one signal; items across families are treated as
independent observations.

Semantic families are also explicit: a cluster of graph rows retrieved by the
same query about the same subject is one family, regardless of row count.
"""
from __future__ import annotations

from backend.models import EvidenceItem, EvidenceSource


def _family_key(ev: EvidenceItem) -> str:
    prov = ev.provenance or {}
    query = str(prov.get("query") or ev.ref or "").split("(")[0]
    # Explicit family tag wins (set by the orchestrator when two queries probe
    # the same underlying fact).
    fam = prov.get("family")
    if fam:
        return str(fam)
    return f"{ev.source.value}:{query}"


def evidence_families(evidence: list[EvidenceItem]) -> list[str]:
    """Return the sorted list of distinct evidence family keys."""
    return sorted({_family_key(ev) for ev in evidence})


def independent_evidence_count(evidence: list[EvidenceItem]) -> int:
    """
    Number of distinct evidence families supporting a case.

    Trigger/customer-reported statements count as their own family only when
    they exist; multiple rows from one graph query stay one family.
    """
    return len(evidence_families(evidence))
