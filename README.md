# HHGoa'26 — Agentic Fraud Investigation

> **An evidence-driven, uncertainty-aware, policy-controlled fraud investigation agent powered by TigerGraph.**

[![Test Suite](https://img.shields.io/badge/pytest-228%20passed-brightgreen.svg)](docs/TECHNICAL_VALIDATION.md)
[![IEEE Checkpoints](https://img.shields.io/badge/IEEE%20Checkpoints-600%2F600%20(100%25)-blue.svg)](artifacts/benchmark/benchmark_report.md)
[![TigerGraph](https://img.shields.io/badge/TigerGraph-Savanna%20Cloud%20Live-orange.svg)](https://savanna.tgcloud.io)
[![Status](https://img.shields.io/badge/Status-FROZEN-success.svg)](artifacts/TECHNICAL_FREEZE.md)

---

## 1. Problem
In modern financial institutions, transaction fraud models flag millions of transactions daily. However:
- **A risk score is an input, not an answer.** High risk scores often represent legitimate emergency spending, while coordinated fraud syndicates deliberately test cards with low-scoring micro-transactions.
- **Siloed tabular data misses interconnected topologies.** Syndicates operate across shared devices, burner phones, multiple identity profiles, and linked credit cards that tabular machine learning cannot detect.
- **LLMs hallucinate ungrounded facts.** Generative models lack deterministic graph reasoning and cannot reliably enforce regulatory compliance or institutional fraud policies without strict grounding.

## 2. Solution
We built an enterprise-grade **Agentic Fraud Investigation Platform** powered by **TigerGraph Savanna Cloud**. The agent:
1. Ingests fraud triggers from the bank's alert feed.
2. Traverses multi-hop entity graphs using **GSQL GraphRAG** to discover hidden device-sharing and multi-card syndicates.
3. Quantifies fraud probability through an explainable **Noisy-OR probabilistic decomposition**.
4. Recognizes when evidence is incomplete, triggering an **Uncertainty Loop** that requests verification and reassesses probability.
5. Recommends **Governed Next Best Actions (NBA)** gated by strict bank fraud policies and human-in-the-loop permission tiers (`auto`, `L1`, `L2`).
6. Persists every completed investigation back into TigerGraph as an `InvestigationCase` vertex, building continuous organizational memory.

---

## 3. Why TigerGraph
TigerGraph provides the foundational computational backbone for this investigation architecture:
- **Native Parallel Graph (NPG):** Deep multi-hop traversals across 590k+ transactions and 144k+ identity records execute in milliseconds.
- **Compiled GSQL Queries:** Custom queries such as `device_neighbors` traverse 2-hop device co-usage topologies in ~40ms to detect distributed card-not-present fraud rings.
- **Dynamic Case Memory:** The graph schema hosts both the transactional dataset and the evolving institutional memory of all past investigations.
- **Model Context Protocol (MCP) & RESTPP:** Clean programmatic integration allowing autonomous agents to query graph facts as callable tools.

---

## 4. What the Agent Does
The agent replaces manual, hours-long fraud triage with an auditable 8-stage investigation pipeline:
1. **Trigger Ingestion**: Parses transaction metadata, dollar amounts, and baseline model risk.
2. **Graph Memory Retrieval**: Queries TigerGraph for historical cardholder velocity, linked devices, and prior confirmed fraud incidents.
3. **Graph Traversal (GSQL)**: Executes 2-hop neighborhood traversals to discover shared infrastructure.
4. **Evidence Synthesis**: Synthesizes and tags all evidence items with immutable IDs and claim classifications (`OBSERVED FACT`, `DERIVED INFERENCE`, `MODEL SCORE`).
5. **Pattern Reasoning**: Evaluates evidence against known fraud archetypes (`card_not_present_fraud`, `account_takeover`, `bust_out`, etc.), capturing primary and secondary candidates.
6. **Noisy-OR Risk Assessment**: Fuses multi-channel risk signals into an explainable mathematical probability.
7. **Uncertainty Evaluation**: When signals conflict, formulates structured inquiries to gather clarifying evidence.
8. **Policy Gating & Action Routing**: Evaluates institutional policy rules, rejects invalid alternatives, and files regulatory Suspicious Activity Reports (SAR) where required.

---

## 5. End-to-End Investigation Flow

```
[ Trigger Event ]
       │
       ▼
[ Investigation Orchestrator ]
       │
       ├─► [ Live TigerGraph Query ] ──► (device_neighbors, card history, prior cases)
       │
       ▼
[ Evidence Synthesis ] ─────────────► Tagged as OBSERVED FACT / DERIVED INFERENCE / MODEL SCORE
       │
       ▼
[ Pattern Reasoning Engine ] ───────► Primary Pattern + Top Candidate Recall
       │
       ▼
[ Noisy-OR Risk Decomposition ] ────► Multi-channel probabilistic aggregation
       │
       ▼
[ Uncertainty & Reassessment ] ─────► Request customer verification ──► Reassess probability
       │
       ▼
[ Governed Policy Engine ] ─────────► Evaluate Rules R1–R4 ──► Log rejected alternatives
       │
       ▼
[ Human Approval Gating ] ──────────► Auto-execute / L1 Team Lead / L2 Fraud Manager
       │
       ▼
[ Graph Memory Persistence ] ───────► Persist InvestigationCase vertex to TigerGraph
```

---

## 6. Architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full architectural documentation.

- **Backend:** FastAPI (Python 3.11–3.14) providing asynchronous REST APIs.
- **Graph Storage:** Live TigerGraph Savanna Cloud instance (`fraud_investigation` graph) in strict fail-closed mode (`STRICT_GRAPH_BACKEND=1`).
- **Frontend:** Analyst Command Center single-page application built in HTML5, CSS3 glassmorphism, and dynamic D3.js SVG graph visualization.
- **Policy Enforcement:** Deterministic Python policy engine enforcing Bank Fraud Policy rules independently of LLM suggestions.

---

## 7. Agent Tools, MCP & GSQL
The agent interacts with TigerGraph via compiled GSQL queries and RESTPP endpoints:
- **`device_neighbors(device_id)`**: Discovers cards and customers sharing identical digital hardware.
- **`cases_by_device(device_id)`**: Identifies historical fraud patterns associated with hardware fingerprints.
- **`card_transaction_history(card_id)`**: Calculates cardholder baseline transaction velocity and spending distributions.
- **`customer_fraud_history(customer_id)`**: Uncovers recidivist accounts and prior fraud claims.

---

## 8. GraphRAG & Evidence Grounding
To prevent generative hallucinations:
- **Zero Raw Prompts for Topology:** The LLM is never permitted to guess or generate graph relationships. Graph facts are retrieved via deterministic GSQL queries.
- **Claim Categorization:**
  - `OBSERVED FACT`: Immutable data points directly retrieved from the graph (e.g., transaction timestamps, dollar amounts, shared device IDs).
  - `DERIVED INFERENCE`: Algorithmic conclusions (e.g., burst transaction velocity, velocity anomalies).
  - `MODEL SCORE`: External model inputs.
- **Citations:** Every evidence card cites its exact originating GSQL/MCP query.

---

## 9. Risk and Pattern Reasoning
- **Dual-Tier Pattern Classifier:** Evaluates evidence against primary topologies while retaining secondary candidates. This ensures that complex hybrid attacks (e.g., account takeover transitioning into card-not-present fraud) are fully surfaced to analysts.
- **Explainable Noisy-OR Decomposition:** Rather than outputting an opaque score, the system decomposes risk across independent channels:
  - Transaction Velocity Burst
  - Network Linkage / Card Sharing
  - Device Anomaly
  - Geolocation Discrepancy
  - Historical Cleared False Alarms (Clearing Channel)

---

## 10. Uncertainty & Additional Evidence Loop
When fraud probability falls within the borderline zone ($0.35 \le P < 0.70$) or conflicting signals exist:
1. The agent marks the investigation as **Uncertain**.
2. It formulates a concrete **Evidence Request** (e.g., `VERIFY_WITH_CUSTOMER`).
3. Upon receiving a response (simulated under competition guidelines), the engine triggers a **Second-Pass Reassessment**.
4. The Command Center displays a clear **Before vs. After** state showing how customer verification altered the probability and changed the recommended action.

---

## 11. Next Best Action (NBA)
The platform derives structured, legally defensible action recommendations:
- **Recommended Action:** e.g., `BLOCK_CARD`, `DECLINE_TRANSACTION`, `MONITOR_CARD`, `CREATE_CASE`, `FILE_REPORT`.
- **Policy Justification:** Cites the exact Bank Fraud Policy rule (e.g., `Policy §3a`, `Rule R1`, `Rule R4`).
- **Expected Impact:** Summarizes the operational consequence (e.g., *"Blocks re-presentation of the disputed transaction"*).
- **Alternatives Rejected:** Explicitly explains why harsher or more lenient measures were ruled out (e.g., *"BLOCK_CARD rejected: no customer confirmation of fraud; monitoring is proportionate"*).

---

## 12. Policy and Approval Governance
Institutional safety is maintained through strict permission tiering:
- **`auto`**: Low-impact actions (case creation, customer notification, account monitoring).
- **`L1` (Team Lead)**: Moderate-impact actions (transaction decline).
- **`L2` (Fraud Manager)**: Severe interventions (card blocking, account freezing, SAR regulatory filings).
- **Enforcement Barrier:** The frontend cannot bypass backend policy; approval endpoints verify authorization and generate immutable audit log entries.

---

## 13. Case Memory / InvestigationCase
Every completed investigation writes an `InvestigationCase` vertex directly back to the TigerGraph schema:
- Linked to the `Customer`, `Card`, and affected `Transaction` nodes.
- Preserves verdict, fraud probability, pattern, SAR filing status, and evidence IDs.
- Subsequent investigations automatically retrieve these vertices during historical lookups, ensuring the institution learns from every investigation.

---

## 14. Analyst Command Center
A single-page command center provides analysts with full operational visibility:
- **Dynamic Case Selector**: Switch between benchmark cases instantly.
- **Causal Story Ribbon**: 8-stage visual progression showing investigation evolution.
- **Interactive Graph Canvas**: Force-directed D3 SVG network graph with pan, zoom, reset, and entity property inspector drawer.
- **Toast System**: Clean non-blocking notifications for operational events.

---

## 15. Benchmark Validation

The platform was evaluated against the official 20-case IEEE-CIS fraud benchmark pack (`HHG-001` through `HHG-020`) under strict live TigerGraph validation:

| Metric | Measured Result | Performance | Evaluation Notes |
|---|:---:|:---:|---|
| **Total Cases Executed** | 20 / 20 | **100%** | Zero crashes, timeouts, or unhandled errors |
| **IEEE Checkpoint Pass Rate** | 600 / 600 | **100%** | All regulatory, data, and policy checkpoints verified |
| **Verdict Accuracy** | 19 / 20 | **95.0%** | Ground-truth fraud vs. cleared determination |
| **Pattern Candidate Recall** | 18 / 20 | **90.0%** | Correct pattern present in candidate reasoning |
| **Primary Pattern Match** | 18 / 20 | **90.0%** | Exact match via generalized evidence-grounded tiebreakers |
| **SAR Determination Accuracy** | 18 / 20 | **90.0%** | Exact alignment with regulatory filing thresholds |
| **Next Best Action (NBA) Accuracy** | 15 / 20 | **75.0%** | Governed action recommendation matching bank policy |
| **TigerGraph Graph Persistence** | 20 / 20 | **100%** | 20 `InvestigationCase` vertices persisted to live graph |
| **Automated Test Suite** | 228 / 228 | **100%** | Full pytest regression suite passing in ~44s |

> **Transparency Note on Pattern Accuracy:** Primary pattern match is **90.0% (18/20)**. The two remaining non-matching cases are strictly grounded in official challenge definitions without benchmark-specific hardcoding:
> - **HHG-009**: An isolated low-dollar dispute ($30.02 vs $61.17 card average) with zero online burst within 48h, sharing a device fingerprint across 20 other cards. Classified as `undocumented` coordinated abuse rather than forced CNP fraud, per Policy R9.
> - **HHG-011**: Three micro-authorizations ($6.33, $6.39, $6.35) preceding a larger purchase ($131.30), strictly matching the official `card_testing` sequence definition, with `card_not_present_fraud` retained as a strong secondary candidate (score 0.50).

---

## 16. Security & Fail-Closed Behavior
- **Zero Secrets in Code:** Scanned and verified across all repository files.
- **Strict Backend Mode (`STRICT_GRAPH_BACKEND=1`):** If TigerGraph Savanna is unreachable, the system raises an explicit HTTP 503 rather than silently fabricating mock results.
- **Safe Logging:** Structlog cleanses authorization headers and secret tokens from all logs.

---

## 17. Repository Structure
```text
├── backend/                     # FastAPI application & agentic pipeline
│   ├── agents/orchestrator.py  # Multi-agent investigation coordinator
│   ├── graph/                  # TigerGraph Savanna live adapter & GSQL client
│   ├── policies/engine.py      # Bank Fraud Policy engine (R1–R10)
│   ├── risk/                   # Noisy-OR assessment & pattern detectors
│   ├── models/                 # Pydantic schemas, evidence & NBA models
│   └── main.py                 # FastAPI application routes
├── frontend/                    # Analyst Command Center SPA
│   ├── index.html              # Command Center layout & modals
│   ├── css/style.css           # Glassmorphism dark-mode styling
│   └── js/                     # Application logic & D3 graph renderer
├── cases/                       # 20 official benchmark answer files (HHG-001–020)
├── artifacts/                   # Audit reports, freeze markers, benchmark results
│   ├── benchmark/              # Benchmark summaries & failure analysis
│   ├── TECHNICAL_FREEZE.md     # Official code freeze marker
│   ├── pre_demo_technical_freeze_report.md
│   └── browser_e2e_judge_report.md
├── docs/                        # Architecture, demo walkthrough, validation docs
│   ├── ARCHITECTURE.md         # Detailed system architecture
│   ├── DEMO.md                 # 3–5 minute judge demonstration script
│   └── TECHNICAL_VALIDATION.md # Comprehensive test & benchmark proof
├── tests/                       # 228 automated tests (unit & integration)
├── requirements.txt             # Pinned production dependencies
└── pyproject.toml               # Project metadata & test configuration
```

---

## 18. Setup & Installation

### Prerequisites
- Python 3.11, 3.12, 3.13, or 3.14
- Git
- Active TigerGraph Savanna Cloud workspace with `fraud_investigation` graph

### Installation
```bash
# Clone the repository
git clone https://github.com/shaikmohammedyasin-create/HHGoa26-Agentic-Fraud-Investigation.git
cd HHGoa26-Agentic-Fraud-Investigation

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 19. Configuration
Create a `.env` file in the root directory (see `.env.example`):
```ini
TG_HOST=https://your-domain.i.tgcloud.io
TG_GRAPH=fraud_investigation
TG_SECRET=your_savanna_secret_token
STRICT_GRAPH_BACKEND=1
APP_PORT=8000
```

---

## 20. Running Locally
Start the server:
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
- **Command Center:** Open [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **API Documentation (Swagger):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Endpoint:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 21. TigerGraph Requirements
The platform connects to a live TigerGraph Savanna Cloud instance configured with:
- **Graph Name:** `fraud_investigation`
- **Schema:** 8 vertex types, 14 edge types
- **Installed Queries:** `device_neighbors`, `cases_by_device`
- **Dataset Scale:** 590,742 transactions, 144,432 identity records, 5,565 closed cases

> **Dataset Reproducibility Note:** The raw source dataset `transactions.csv` (~708 MB) is intentionally excluded from the Git repository due to GitHub file size limitations. The live evaluation graph in TigerGraph Savanna has already been fully populated and indexed.

---

## 22. Live Demonstration
See [docs/DEMO.md](docs/DEMO.md) for the complete 3–5 minute step-by-step presentation script.
1. Select case **`HHG-001`**.
2. Click **`Start Live Investigation`**.
3. Observe live GSQL graph traversal, evidence synthesis, and Noisy-OR breakdown.
4. Inspect the **Uncertainty Loop** and **Governed NBA** recommendations.
5. Click graph nodes to inspect metadata in the **Graph Inspector**.

---

## 23. Official Benchmark Outputs
The 20 official benchmark answer files are stored in `cases/`:
`cases/HHG-001.json` through `cases/HHG-020.json`.
Each answer file contains:
- Complete internal investigation record
- Live TigerGraph persistence status & graph case ID
- Suspicious Activity Report (SAR) filing determination
- Next Best Action (NBA) with approval routes before and after additional evidence
- Full evidence provenance chain and stopping criteria

To instantly compare all 20 benchmark case outputs against expected baseline criteria:
```bash
python scripts/compare_metrics.py
```

---

## 24. Known Limitations
- **Savanna Cloud Idle Suspension:** Free-tier TigerGraph Savanna clusters automatically suspend after 60 minutes of inactivity. The workspace must be resumed in TGCloud before testing.
- **Network Roundtrip:** GSQL query latency depends on Internet connectivity to AWS us-east-1 (~35–85ms).
- **Simulated External Actors:** Customer verification and analyst escalation responses during the benchmark are simulated in accordance with competition rules.
- **Hackathon Scope:** Engineered as a high-fidelity prototype; not certified for automated production card blocking without human-in-the-loop oversight.

---

## 25. What We Would Improve With More Time
- **Dynamic Multi-Cluster Graph Partitioning:** Graph clustering algorithms (e.g., Louvain or Weakly Connected Components) to identify entire fraud rings in a single query.
- **Real-Time Customer Verification Webhooks:** SMS/Push notification webhooks replacing simulated verification responses.
- **Automated SAR E-Filing XML Generator:** FinCEN-compliant XML payload generation for seamless submission to regulatory gateways.

---

## 26. Team & Attribution
- **Competition:** TigerGraph × Hacker House Goa 2026 (HHGOA'26)
- **Track:** Agentic Fraud Investigation (IEEE-CIS Edition)
- **Dataset:** Vesta Corporation / IEEE-CIS Fraud Detection Dataset
