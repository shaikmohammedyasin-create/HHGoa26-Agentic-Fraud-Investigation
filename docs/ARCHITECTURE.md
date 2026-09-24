# System Architecture

The **TigerGraph Agentic Fraud Investigation System** is an enterprise-grade, multi-agent GraphRAG platform engineered for fraud triage, root-cause investigation, and regulatory compliance under strict bank policy governance.

```
                    ┌─────────────────────────────────────────┐
                    │       Analyst Command Center (UI)       │
                    │  (Dynamic SVG Graph, Inspector, Toasts) │
                    └────────────────────┬────────────────────┘
                                         │ HTTP REST APIs
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │       FastAPI Gateway & Endpoints       │
                    │  (/api/cases, /investigations, /graph)  │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Agentic Investigation Engine                          │
│                                                                             │
│  1. Trigger Ingestion ──► 2. Graph Traversal & Evidence Retrieval           │
│                                 │ (pyTigerGraph / GSQL / device_neighbors)  │
│                                 ▼                                           │
│  4. Risk Aggregation ◄── 3. Pattern Reasoning (Primary & Candidates)        │
│     (Noisy-OR Channels)         │                                           │
│          │                      ▼                                           │
│          ▼             5. Uncertainty Detection & Evidence Request          │
│  6. Reassessment ◄──────────────┤ (Customer Verification / Multi-hop)       │
│          │                                                                  │
│          ▼                                                                  │
│  7. Governed Next Best Action (NBA) ──► 8. Policy Engine (Rules R1–R4)      │
│                                               │                             │
│                                               ▼                             │
│  9. Regulatory SAR Filing ◄────────── 10. Human Approval Gating             │
│                                           (Auto / L1 Lead / L2 Manager)     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Authoritative Storage Layer                          │
│                                                                             │
│  ┌─────────────────────────────────┐   ┌─────────────────────────────────┐  │
│  │     TigerGraph Savanna Cloud    │   │      Local SQLite Metadata      │  │
│  │    (Graph: fraud_investigation) │   │     (data/app/app.db cache)     │  │
│  │   8 Vertices, 14 Edges, GSQL    │   │     Audit Logs & Timelines      │  │
│  │  Case Memory: InvestigationCase │   │                                 │  │
│  └─────────────────────────────────┘   └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Subsystems

### 1. TigerGraph GraphRAG Retrieval
- Authoritative topology: 590,742 transactions, 144,432 identity records, and 5,565 closed historical cases.
- Real-time installed GSQL queries:
  - `device_neighbors`: 2-hop co-usage query linking devices to cards across the network.
  - `cases_by_device`: Rapid historical lookup for prior fraud association.
- Fail-Closed Mode: In `STRICT_GRAPH_BACKEND=1`, queries must execute against live TigerGraph. No silent mock fallbacks.

### 2. Evidence Provenance & Categorization
Every piece of data that enters the reasoning pipeline receives a unique identifier (`EV-xxxxxxxx`) and is tagged by **Claim Type**:
- `OBSERVED FACT`: Explicit, immutable graph facts (transaction timestamps, dollar amounts, shared device IDs).
- `DERIVED INFERENCE`: Algorithmic patterns (velocity burst, fraud-ring membership, memory-derived signals).
- `MODEL SCORE`: External upstream bank risk score ($0 \le S \le 1$).

**Evidence independence** is computed by clustering evidence into provenance families (`backend/risk/independence.py`): items from the same query probing the same underlying signal are one family; only cross-family items count as independent. The independent-evidence count feeds confidence and the stopping criteria, so reported independence reflects real signal diversity rather than source-string counts.

### 3. Risk Assessment via Noisy-OR Decomposition
Fraud probability is calculated using an explainable probabilistic Noisy-OR formulation:
$$P(\text{Fraud}) = 1 - \prod_{i \in \text{channels}} (1 - w_i) \cdot \frac{1}{\prod_{j \in \text{clearing}} f_j}$$
where clearing factors $f_j > 1$ multiply $P(\text{not fraud})$ and therefore lower the fraud probability. Decomposed into distinct risk channels:
- Transaction Velocity Burst
- Network Linkage / Multi-card Association
- Device Profile Anomaly / Shared Device Risk
- Geolocation Distance
- **Fraud Ring** (connected-component fraud membership via `device_fraud_ring`)
- **Agent Case Memory** (prior agent investigations ending in confirmed fraud)
- **Additional-evidence outcomes** (step-up auth failure, analyst / watchlist results)
- Historical Cleared False Alarms (Clearing Channel, correct multiplicative direction)

### 4. The Evidence-Gap & Reassessment Loop (information-value based)
When an initial assessment is borderline, the agent does not simply ask the customer:
1. The **evidence-gap engine** enumerates candidate requests relevant to the case's signals
   (customer validation, step-up auth, analyst info, external watchlist).
2. Each candidate is scored by **expected decision impact**: the engine computes the policy
   action set under both plausible outcomes via the real Noisy-OR channels and measures the
   severity-weighted divergence between them. Evidence that cannot change the decision is
   suppressed (`MIN_EVIDENCE_INFO_VALUE`, default 0.25).
3. The selected request records `info_value`, alternatives with scores, and the hypotheses
   it could flip — full selection provenance on every `EvidenceRequest`.
4. **Two modes** (`EVIDENCE_REQUEST_MODE`): `human_in_loop` pauses the persisted state
   machine at `MORE_EVIDENCE_REQUIRED` until `POST /investigations/{id}/evidence` supplies
   a real response; `simulated` generates a deterministic synthetic response always labelled
   `origin=simulated`.
5. **Reassessment** rebuilds the risk from the persisted signal snapshot (in
   `case.signal_store`), updates probability/risk/uncertainty, and marks resolved
   uncertainties with `resolved_by` + `resolution_impact`.

### 4b. Hybrid Planner
Tool selection is not a fixed script. `backend/agents/planner.py` plans per round:
- Round 0: subject + baseline tools (always).
- Round 1: conditional tools chosen by open evidence gaps — device traversals and
  `device_fraud_ring` only when a device exists, region-window only on a new region,
  velocity only on online activity.
- Round 2: GraphRAG retrieval (pattern + tokenised keyword search).
Every plan (tools, gap, rationale) is appended to `case.plan_trace` for audit. The LLM,
when configured, never selects tools — decisions stay deterministic.

### 5. Policy Engine & Approval Governance
Recommendations are strictly separated into three concerns:
1. **AI Suggestion**: Proposes optimal interventions based on risk signals.
2. **Policy Enforcement**: Evaluates Bank Fraud Policy rules (Policy §3a, R1–R11) including:
   - **R11 (uncertainty-aware selection)**: on a low-confidence borderline assessment with
     high-value unrequested evidence, prefer gathering that evidence over acting.
   - **why_now**: every recommendation states what in the current state makes it the right
     action at this moment.
3. **Approval Gating**: Gated into permission tiers:
   - `auto`: Automated case creation, cardholder notification, or low-risk monitoring.
   - `L1`: Team Lead authorization required for transaction declines.
   - `L2`: Fraud Manager authorization required for card blocking or SAR filing.
   - *Alternatives Rejected*: Explicitly logs why harsher or more lenient actions were ruled out.
4. **Approval decisions execute**: an approval is re-validated against the policy table at
   decision time; approving executes the action under the approver's authority with
   `approval_granted` + `action_executed` audit events; rejecting records
   `approval_rejected`. Decided approvals cannot be re-decided.

### 6. Case Memory & Graph Persistence
Every completed investigation writes an `InvestigationCase` vertex directly back to the live TigerGraph schema, linking it to the customer, card, affected transactions **and involved device profiles (`IC_ON_DEVICE`)**. Future investigations query this case memory during historical retrieval via `investigation_cases_for_customer`, and the retrieved prior agent cases feed a dedicated `agent_prior_fraud` Noisy-OR channel plus an evidence item — the institutional memory loop is closed on both the write and the read side.

Case-memory writes are **fail-closed** under the TigerGraph backend: a failed write records `written_to_graph=False` plus a `graph_write_failed` audit event rather than silently persisting locally while the UI claims graph persistence.
