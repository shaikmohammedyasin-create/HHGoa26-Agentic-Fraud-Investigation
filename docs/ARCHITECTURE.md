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
- `DERIVED INFERENCE`: Algorithmic patterns (velocity burst, account takeover indicators).
- `MODEL SCORE`: External upstream bank risk score ($0 \le S \le 1$).

### 3. Risk Assessment via Noisy-OR Decomposition
Fraud probability is calculated using an explainable probabilistic Noisy-OR formulation:
$$P(\text{Fraud}) = 1 - \prod_{i \in \text{channels}} (1 - w_i \cdot s_i) \cdot \prod_{j \in \text{clearing}} (1 - c_j)$$
Decomposed into distinct risk channels:
- Transaction Velocity Burst
- Network Linkage / Multi-card Association
- Device Profile Anomaly / Shared Device Risk
- Geolocation Distance
- Historical Cleared False Alarms (Clearing Channel)

### 4. The Uncertainty & Reassessment Loop
When an initial investigation yields a borderline probability ($0.35 \le P < 0.70$) or conflicting signals:
1. The agent identifies missing information and generates a formal **Evidence Request**.
2. A simulated customer or analyst response is processed.
3. The case undergoes a **Second-Pass Reassessment**, shifting probability and modifying recommended actions before taking irreversible steps.

### 5. Policy Engine & Approval Governance
Recommendations are strictly separated into three concerns:
1. **AI Suggestion**: Proposes optimal interventions based on risk signals.
2. **Policy Enforcement**: Evaluates Bank Fraud Policy rules (Policy §3a, R1, R2, R3, R4).
3. **Approval Gating**: Gated into permission tiers:
   - `auto`: Automated case creation, cardholder notification, or low-risk monitoring.
   - `L1`: Team Lead authorization required for transaction declines.
   - `L2`: Fraud Manager authorization required for card blocking or SAR filing.
   - *Alternatives Rejected*: Explicitly logs why harsher or more lenient actions were ruled out.

### 6. Case Memory & Graph Persistence
Every completed investigation writes an `InvestigationCase` vertex directly back to the live TigerGraph schema, linking it to the customer, card, and affected transactions. Future investigations query this case memory during historical retrieval.
