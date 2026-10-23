# Agentic Fraud Investigation Platform

> An autonomous, evidence-grounded, policy-controlled fraud investigation platform powered by TigerGraph GraphRAG, calibrated Bayesian risk scoring, **NVIDIA Nemotron LLMs on Nebius Token Factory**, and human-in-the-loop governance.

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-REST%20API-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://www.tigergraph.com/"><img src="https://img.shields.io/badge/TigerGraph-Savanna%20Cloud-F36C21" alt="TigerGraph"></a>
  <a href="https://build.nvidia.com/nvidia"><img src="https://img.shields.io/badge/NVIDIA-Nemotron_3_%7C_Token_Factory-76B900" alt="NVIDIA Nemotron"></a>
  <a href="./docs/TECHNICAL_VALIDATION.md"><img src="https://img.shields.io/badge/Tests-278%20Passed%20%7C%209%20Skipped-2E7D32" alt="Tests"></a>
  <a href="./docs/BENCHMARK.md"><img src="https://img.shields.io/badge/Benchmark-20%2F20%20Verdict%20%2B%20Pattern%20%7C%20Ablations-2E7D32" alt="Benchmark"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License"></a>
</p>

---

## 0. Quickstart (5 minutes, zero credentials)

```bash
git clone <your-repo-url>
cd <repo>
docker compose up --build
# open http://localhost:8008
```

The container rebuilds its own SQLite graph store from the published synthetic
data (~3 s), runs locally (`GRAPH_BACKEND=local`), and starts in **demo mode**
(`DEMO_MODE=1`): Nemotron advisory answers replay from a local answer cache
and **no API credits are spent**. Judges need nothing but Docker.

For live Nemotron calls, set `NEBIUS_API_KEY` in `docker-compose.yml`
(details in [docs/DEPLOY.md](./docs/DEPLOY.md)).

---

## Table of Contents

0. [Quickstart](#0-quickstart-5-minutes-zero-credentials)
1. [Problem Statement](#1-problem-statement)
2. [Solution Overview](#2-solution-overview)
3. [NVIDIA Nemotron & Nebius Token Factory](#how-we-use-nvidia-nemotron--nebius-token-factory)
4. [Key Capabilities](#3-key-capabilities)
5. [Architecture](#4-architecture)
6. [Agentic Workflow](#5-agentic-workflow)
7. [Technology Stack](#6-technology-stack)
8. [Repository Structure](#7-repository-structure)
9. [Requirements](#8-requirements)
10. [Installation](#9-installation)
11. [Environment Configuration](#10-environment-configuration)
12. [Running Locally](#11-running-locally)
13. [TigerGraph Setup & Configuration](#12-tigergraph-setup--configuration)
14. [API Overview](#13-api-overview)
15. [Investigation Workflow](#14-investigation-workflow)
16. [Testing & Validation](#15-testing--validation)
17. [Security Considerations](#16-security-considerations)
18. [Configuration Options](#17-configuration-options)
19. [Limitations](#18-limitations)
20. [Future Improvements](#19-future-improvements)
21. [License](#20-license)

---

## 1. Problem Statement

Financial fraud detection systems in banks and payment processors face three fundamental operational bottlenecks:

1. **Black-Box Score Opacity**: Machine learning models produce risk scores (e.g., `0.87`) without transparent, verifiable explanations. Fraud analysts cannot immediately see *why* an alert triggered or what underlying graph connections justify blocking a card or declining a transaction.
2. **Investigation Fatigue & High False Positives**: Analysts manually query multiple disjoint systems—card records, device fingerprints, transaction logs, merchant histories, and previous dispute records—to build context. This manual multi-hop correlation creates investigation latency and inconsistent decisions.
3. **Absence of Governed Action Enactment**: Alerts are frequently disconnected from institutional banking policy. Without deterministic policy gating, recommended actions risk either unauthorized auto-execution (causing customer friction) or delayed intervention (causing financial exposure).

---

## 2. Solution Overview

The **Agentic Fraud Investigation Platform** converts raw transactional fraud alerts into complete, auditable, and policy-governed investigations:

$$\text{Alert} \longrightarrow \text{Graph Evidence} \longrightarrow \text{Pattern Reasoning} \longrightarrow \text{Risk Decomposition} \longrightarrow \text{Uncertainty Loop} \longrightarrow \text{Governed NBA} \longrightarrow \text{Human Approval} \longrightarrow \text{Graph Case Memory}$$

The platform integrates:
- **TigerGraph Savanna Cloud / GSQL Engine**: High-performance multi-hop graph traversal that links customers, cards, transactions, device profiles, and billing regions.
- **GraphRAG Evidence Retrieval**: Contextual retrieval across previous investigation cases, fraud rings, and institutional banking policies.
- **Adaptive Agent Planner**: An autonomous orchestrator that dynamically selects investigation tools based on open evidence gaps rather than executing a hardcoded sequence.
- **Explainable Noisy-OR Risk Modeling**: Calibrated Bayesian odds aggregation across independent evidence channels (device sharing, velocity bursts, historical dispute records, customer responses).
- **Human-in-the-Loop (HITL) Governance**: Strict role separation (Auto-Execution, Level 1 Team Lead, Level 2 Operations Manager) with immutable SQLite audit logging.
- **Closed-Loop Graph Memory**: Every completed investigation is written back to TigerGraph as an `InvestigationCase` vertex, allowing future investigations to leverage prior findings.

---

## How We Use NVIDIA Nemotron & Nebius Token Factory

NVIDIA **Nemotron 3** reasoning models, served through **Nebius Token
Factory** (`https://api.tokenfactory.nebius.com/v1`, OpenAI-compatible), add
language intelligence on top of the deterministic investigation engine —
they are treated as *advisors*, never as the decision-maker:

| # | Role | Verb | Tier / Model | Why this model |
|---|---|---|---|---|
| 1 | **Pattern classifier** | Proposes a fraud pattern (card-not-present, ATO, card-testing, …) with confidence, evidence ids, and a rationale grounded ONLY in the finite evidence set | Nano — `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 20+ fast high-volume calls per run; cheapest tier |
| 2 | **Verification request drafter** | Drafts the human-readable "verify with customer" message an analyst sends | Nano | Many short drafts |
| 3 | **Narrative + SAR drafter** | Produces the SAR narrative and case story from the evidence record | Ultra — `nvidia/Nemotron-3-Ultra-550b-a55b` | Long-context reasoning + writing quality |
| 4 | **Analyst Q&A** | Answers arbitrary analyst questions about a case (advisory tab) | Ultra | Free-form reasoning over case facts |

Design principles:

- **Propose, never decide.** The model's pattern proposal (role 1) is stored
  next to the policy engine's decision (`model_proposal` vs
  `policy_decision`) with an explicit `model_agreed` flag and
  `model_override_reason`. The deterministic rules (R1–R10) remain the
  single source of truth — measurable ablation in
  [docs/BENCHMARK.md](./docs/BENCHMARK.md) section D.
- **Prompt-injection hardening.** Case text (customer statements, trigger
  text, notes) is treated as untrusted data; role prompts instruct the
  model to reject instructions embedded in evidence, and this is enforced
  by tests (`tests/integration/test_nemotron_roles.py`).
- **Fail-soft.** Every call has a 30 s timeout, 2 retries, and an explicit
  `None` fallback contract: any Token Factory outage degrades to the
  deterministic path, never a 5xx.
- **Token-Factory-specific hardening.** Reasoning-style models spend hidden
  reasoning tokens before visible output. Generous `max_tokens`
  (1,200–2,048) and an explicit `ANSWER:` output contract for Q&A prevent
  truncated or leaking responses (verified live against the endpoint).
- **Cost governance.** Demo-mode answer cache (zero-credit replays),
  per-IP hourly limiter, global daily cap, and a JSONL per-call log with
  p50/p95 latency surfaced live on `/api/llm/status`.

---

## 3. Key Capabilities

### Live Graph Traversal & Topology Analysis
- **Multi-Hop Traversal**: Discovers shared devices, card networks, and account clusters across hundreds of thousands of transactions.
- **Fraud-Ring Component Detection**: Analyzes connected graph components to detect organized fraud rings and syndicated card testing.
- **Strict Backend Mode**: Enforces fail-closed operation (`STRICT_GRAPH_BACKEND=1`), ensuring production environments never silently fall back to mock data if the authoritative database is unavailable.

### Provenance-Aware Evidence Assembly
Every evidence item is cataloged with an immutable evidence identifier, claim classification, and query reference:
- `OBSERVED FACT`: Directly queried graph properties (e.g., historical transaction count, device profile matches).
- `DERIVED INFERENCE`: Algorithmic conclusions (e.g., velocity anomalies, fraud ring membership).
- `MODEL SCORE`: Upstream detection model inputs.

### Nemotron Advisory (propose / decide separation)
- The **Nemotron Advisory tab** surfaces the model's pattern proposal with
  confidence, evidence citations, rationale, and an explicit
  agreed / overruled badge next to the policy engine's decision.
- Analysts can **ask arbitrary questions** about any case in the "Ask"
  box; answers come from Token Factory (Ultra tier) with an `ANSWER:`
  contract and are stamped "model-served" in the footer.
- Role 2 drafts the customer-verification message shown in the Uncertainty
  tab; role 3 drafts the SAR narrative first-person story (tagged "Part II:
  Nemotron draft").
- Everything is advisory: no model output mutates the deterministic policy
  decisions without a recorded engine justification.

### Active Uncertainty & Evidence-Gap Reduction
- Evaluates expected information value ($0.0 - 1.0$) for potential follow-up inquiries.
- Determines whether gathering additional evidence (customer confirmation, step-up authentication, merchant records) could change the recommended action.
- Supports both `human_in_loop` (agent pauses at `MORE_EVIDENCE_REQUIRED` waiting for analyst input) and `simulated` (generates transparent, audit-marked synthetic responses).

### Policy-Governed Next Best Action (NBA)
- Deterministic rules engine enforcing institutional banking policies (§3 R1–R11).
- Generates concrete remediation recommendations: `BLOCK_CARD`, `DECLINE_TRANSACTION`, `FILE_REPORT` (SAR), `MONITOR_CONNECTED_CARDS`, `REQUEST_CUSTOMER_CONFIRMATION`, and `CLOSE_NO_FRAUD`.
- Documents policy citations, current state justifications, and evaluated alternatives.

### Analyst Command Center
- **Interactive Knowledge Graph Canvas**: HTML5 canvas rendering subgraphs with force-directed physics, node clustering, and entity inspectors.
- **Visual Causal Journey**: 11-stage progress tracker illustrating trigger ingestion, planning, evidence collection, risk reassessment, and action approval.
- **Regulatory SAR Generator**: Prepares Suspicious Activity Report (SAR) narratives citing timestamped evidence, exposure totals, and subject cards/devices.

---

## 4. Architecture

The system consists of five decoupled layers designed for modularity, observability, and testability:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Analyst Command Center (Web UI)                      │
│        Case Dossier • Dynamic Graph Canvas • Risk Breakdown • SAR      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP REST / JSON
┌───────────────────────────────────▼────────────────────────────────────┐
│                       FastAPI Application Gateway                      │
│        /investigations • /evidence • /approvals • /graph • /health     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                       Agentic Investigation Engine                     │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────────┐  │
│  │   Planner    │──▶│ Query Router   │──▶│ Pattern Reasoning        │  │
│  └──────────────┘   └────────────────┘   └──────────────────────────┘  │
│         │                   │                         │                │
│         ▼                   ▼                         ▼                │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────────────────┐  │
│  │ Evidence Gap │   │ Noisy-OR Risk  │   │ Policy Engine (NBA)      │  │
│  └──────────────┘   └────────────────┘   └──────────────────────────┘  │
└───────────────────────┬───────────────────────────────┬────────────────┘
                        │                               │
┌───────────────────────▼──────────────┐ ┌──────────────▼────────────────┐
│   TigerGraph Savanna Cloud / Local   │ │    SQLite Application State   │
│   Vertices: Customer, Card, Txn...   │ │    Investigations, Approvals, │
│   Edges: OWNS, MADE, FROM_DEVICE...  │ │    Idempotency, Audit Trail   │
└──────────────────────────────────────┘ └───────────────────────────────┘
```

![Architecture Diagram](./docs/images/archi.png)

---

## 5. Agentic Workflow

The autonomous investigation engine executes through an iterative, evidence-grounded state machine:

![Investigation Flow](./docs/images/simplified_flow.png)

1. **Trigger Ingestion**: Receives an incoming alert (real-time transaction scoring anomaly or customer dispute report).
2. **Planner Strategy Selection**: Formulates an initial tool execution plan based on alert category and transaction attributes.
3. **Graph Traversal & GraphRAG Retrieval**: Executes GSQL queries against the graph database to retrieve customer history, card baseline statistics, device co-usage, and similar closed historical cases.
4. **Pattern Typology Classification**: Detects recognized fraud typologies (`card_not_present_fraud`, `card_not_present_new_device`, `account_takeover`, `card_testing`).
5. **Noisy-OR Risk Decomposition**: Aggregates independent risk channels into a calibrated composite fraud probability.
6. **Evidence Gap Identification**: Calculates residual uncertainty and scores potential evidence requests by decision impact.
7. **Reassessment Loop**: Incorporates additional evidence (e.g., customer verification) and updates Bayesian odds.
8. **Policy Engine Evaluation**: Validates facts against institutional policies to determine required actions and assign permission levels.
9. **Approval & Execution Routing**: Executes auto-approved actions immediately; enqueues high-impact actions (card blocks, SAR filings) for Level 1 or Level 2 human approval.
10. **Case Memory Persistence**: Creates an `InvestigationCase` vertex in the graph database to inform future anomaly detection.

---

## 6. Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **Backend API** | Python 3.11+, FastAPI, Pydantic v2 | High-performance asynchronous REST API with strict type validation |
| **Graph Database** | TigerGraph Savanna Cloud 4.x, GSQL | High-performance graph database optimized for deep multi-hop pattern analytics |
| **Graph Adapter** | pyTigerGraph, httpx | Connection pooling, token management, and REST API fallbacks |
| **State Persistence** | SQLite 3 | Embedded, durable relational store for application state and audit trails |
| **Frontend UI** | HTML5, CSS3, Vanilla ES6 JavaScript | Zero-build-step intelligence console with minimal footprint and maximum auditability |
| **Graph Visualization** | HTML5 Canvas API | High-performance physics-based graph layout without bulky heavy external dependencies |
| **Test Runner** | Pytest, pytest-asyncio, anyio | Comprehensive test suite covering unit, integration, and policy contracts |

---

## 7. Repository Structure

```
.
├── backend/                        # Backend Python service
│   ├── agents/                     # Agent implementations
│   │   ├── evidence_gap.py         # Evidence gap detection & info-value ranking
│   │   ├── orchestrator.py         # Multi-stage investigation coordinator
│   │   └── planner.py              # Adaptive tool-planning engine
│   ├── db/                         # SQLite application database & audit log
│   ├── evaluation/                 # Benchmark runners & answer validators
│   ├── graph/                      # Graph access layer
│   │   ├── local_store.py          # Prepared SQLite graph store (local/test)
│   │   ├── query_router.py         # Intelligent graph backend abstraction
│   │   └── tg_adapter.py           # TigerGraph Savanna Cloud adapter
│   ├── graphrag/                   # Context assembly & case-note search
│   ├── llm/                        # Optional narrative generation client
│   ├── models/                     # Pydantic data schemas
│   ├── policies/                   # Deterministic banking policy engine (§3 R1–R11)
│   ├── risk/                       # Bayesian Noisy-OR composite risk modeling
│   ├── scripts/                    # Schema deployment and preparation scripts
│   ├── config.py                   # Environment settings & configuration loading
│   ├── logging.py                  # Structured logging configuration
│   └── main.py                     # FastAPI application entrypoint
│
├── frontend/                       # Analyst Command Center (Single Page UI)
│   ├── css/
│   │   └── style.css               # Dark forest green & warm cream design system
│   ├── js/
│   │   ├── api.js                  # Frontend REST API client
│   │   ├── app.js                  # UI state management & event handlers
│   │   └── graph.js                # HTML5 canvas interactive knowledge graph
│   └── index.html                  # Main command center interface
│
├── sentinel-ui/                     # Vendored Sentinel v2 analyst console (Next.js, separate app)
│   ├── src/app/                     # Console, Monitor, Ring, approvals, benchmark views
│   ├── src/components/              # Console shell, role switcher, UI primitives
│   ├── src/lib/                     # API client, SSE hooks, generated backend contract
│   └── NOTICE.md                    # Upstream attribution, license status, known issues
│
├── tigergraph/                     # TigerGraph database assets
│   ├── gsql/                       # GSQL query & algorithm definitions
│   ├── loading/                    # Loading job scripts for tabular ingestion
│   └── schema/                     # DDL schema definitions & schema-change jobs
│
├── cases/                          # 20-case benchmark + ground_truth.json labels
├── tests/                          # Automated test suite (278 passed / 9 skipped)
│   ├── integration/                # API, graph, policy, and agentic upgrade tests
│   └── unit/                       # Risk, policy, and evidence provenance tests
│
├── docs/                           # Documentation
│   ├── backend/                    # Architecture and dataset specifications
│   ├── images/                     # System architecture & flow diagrams
│   ├── ARCHITECTURE.md             # In-depth system architecture
│   ├── DEMO.md                     # Interactive demonstration walkthrough
│   ├── TECHNICAL_VALIDATION.md     # Empirical validation and benchmark results
│   ├── BENCHMARK.md                # Held-out eval: fidelity + ablations + cost/latency
│   └── DEPLOY.md                   # Docker deployment and cost governance
│
├── scripts/                        # Administrative utilities
├── .env.example                    # Environment variable template
├── pyproject.toml                  # Python package configuration
├── requirements.txt                # Pinned production dependencies
└── README.md                       # Project documentation
```

---

## 8. Requirements

- **Operating System**: Linux, macOS, or Windows 10/11
- **Docker** (recommended path, includes everything): `docker compose up --build`
- **Python**: Version `3.11` or higher
- **Browser**: Modern web browser (Chrome, Edge, Firefox, Brave)
- **TigerGraph** (Optional; the demo runs on `GRAPH_BACKEND=local` by default):
  - TigerGraph Savanna Cloud or on-premises instance (version 4.x)
- **LLM API Key** (Optional — demo mode needs none):
  - **Nebius Token Factory** API key (`NEBIUS_API_KEY`) for live NVIDIA
    Nemotron advisory calls. Without it the system runs in demo mode
    (cached answers) and always falls back to deterministic output.

---

## 9. Installation

### 1. Clone the repository

```bash
git clone https://github.com/shaikmohammedyasin-create/HHGoa26-Agentic-Fraud-Investigation.git agentic-fraud-investigation
cd agentic-fraud-investigation
```

### 2. Set up a virtual environment

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 10. Environment Configuration

```bash
cp .env.example .env
```

Key variables (full list in `.env.example` and [`docs/DEPLOY.md`](./docs/DEPLOY.md)):

```env
# Graph Backend (local | tigergraph)
GRAPH_BACKEND=local
STRICT_GRAPH_BACKEND=false

# TigerGraph Settings (only if GRAPH_BACKEND=tigergraph)
TG_HOST=https://your-instance.i.tgcloud.io
TG_GRAPH=fraud_investigation
TG_SECRET=your_tigergraph_secret
TG_PORT=443
TG_PROTOCOL=https

# Agentic Evidence Loop (simulated | human_in_loop)
EVIDENCE_REQUEST_MODE=simulated

# NVIDIA Nemotron via Nebius Token Factory (optional - demo mode without it)
NEBIUS_API_KEY=            # leave empty for demo mode
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL_NANO=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
NEBIUS_MODEL_SUPER=nvidia/nemotron-3-super-120b-a12b
NEBIUS_MODEL_ULTRA=nvidia/Nemotron-3-Ultra-550b-a55b

# Demo & cost governance
DEMO_MODE=1                       # 1 = serve cached Nemotron answers, zero credits
LLM_CALLS_PER_IP_PER_HOUR=20      # per-IP hourly limiter
LLM_DAILY_CALL_CAP=200            # global daily cap; deterministic fallback beyond
```

---

## 11. Running Locally

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.scripts.prepare_data                  # build data/prepared/investigation.db (~3 s on synthetic data)
uvicorn backend.main:app --port 8008
```

Open your browser and navigate to:
```
http://localhost:8008
```

The Analyst Command Center will load with system connectivity diagnostics and a
demo-mode banner (when `DEMO_MODE=1`). All 20 cases run without any LLM key;
live Nemotron review happens in the Nemotron Advisory tab when a key is set.

---

### Optional: Vendored Sentinel Console (`sentinel-ui/`)

The repository also ships a vendored copy of Team CollabUp's "Sentinel v2" analyst
console (Next.js + React + Tailwind) as a standalone second UI. It does **not**
replace the primary Analyst Command Center and does not talk to this repository's
backend — it speaks its own contract against the upstream team's deployed API.

```bash
cd sentinel-ui
npm install
# PowerShell: point it at the upstream deployed API (CORS-allowlisted for localhost:3000)
$env:NEXT_PUBLIC_API_BASE = "https://apihacker.collabup.co.in"
npm run dev            # → http://localhost:3000
```

Upstream source, attribution, license status (upstream is unlicensed), and known
issues are documented in `sentinel-ui/NOTICE.md`.

---

## 12. TigerGraph Setup & Configuration

To run against a live TigerGraph instance:

### 1. Deploy the Schema
Deploy vertex and edge definitions to the target graph (`fraud_investigation`):

```bash
python -m backend.scripts.deploy_schema
```

### 2. Compile GSQL Queries
Install and compile the parameterized queries:

```bash
python scripts/deploy_all_queries.py
```

Queries deployed include:
- `card_transaction_history`: 30-day transactional window for card baseline.
- `accounts_sharing_device`: Discovers cards that share hardware/browser fingerprints.
- `device_fraud_ring`: Traverses device co-usage components to detect organized syndicates.
- `closed_cases_by_device`: Retrieves historical confirmed fraud cases linked to a device.
- `insert_investigation_case`: Upserts completed case vertices into the knowledge graph.

---

## 13. API Overview

The backend exposes a structured, typed OpenAPI REST interface:

### System & Health
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Returns service health, graph connectivity, database state, and active configuration |

### Investigations
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/investigations` | Initiates an investigation for a designated case ID |
| `GET` | `/investigations` | Lists recorded investigations with pagination |
| `GET` | `/investigations/{case_id}` | Retrieves standardized investigation answer payload |
| `POST` | `/investigations/{case_id}/run` | Re-runs or resumes an investigation (`force=true` forces a clean rerun) |
| `GET` | `/api/investigations/{case_id}/full` | Retrieves rich investigation state including triggers, evidence cards, and policy decisions |
| `GET` | `/api/investigations/{case_id}/graph` | Generates a scoped subgraph JSON for the canvas visualization engine |
| `GET` | `/investigations/{case_id}/timeline` | Returns timestamped audit events for the investigation |

### Evidence & Human-in-the-Loop
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/investigations/{case_id}/evidence` | Lists evidence items assembled for the case |
| `POST` | `/investigations/{case_id}/evidence` | Submits human evidence to resolve a pending information request |

### Nemotron Advisory & LLM Ops
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/investigations/{case_id}/ask` | Ask-a-question advisory endpoint (Nemotron Ultra with `ANSWER:` contract); fails soft to deterministic context |
| `GET` | `/api/llm/status` | Token Factory ops snapshot: calls, successes/failures, token totals, p50/p95 latency, per-role counts |

### Policy & Approvals
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/investigations/{case_id}/approvals` | Lists pending Level 1 / Level 2 actions requiring authorization |
| `POST` | `/investigations/{case_id}/approvals/{approval_id}` | Records approval or rejection under the analyst's identity |

### Evaluation & Benchmark
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/cases` | Lists available benchmark cases from the case pack |
| `POST` | `/benchmark/run` | Executes the full 20-case evaluation benchmark |
| `GET` | `/benchmark/report` | Returns latest benchmark summary statistics |
| `GET` | `/benchmark/checkpoints` | Returns structural checkpoint compliance metrics (600 checkpoints) |

---

## 14. Investigation Workflow

A typical investigation through the Command Center proceeds as follows:

```
[1. Select Case] ──▶ [2. Ingest Trigger] ──▶ [3. Run Agent Engine] ──▶ [4. Inspect Subgraph]
                                                                                │
[7. Persist Memory] ◀── [6. Authorize Action] ◀── [5. Reassess Risk] ◀──────────┘
```

1. **Select Dossier**: Choose an active case (e.g., `CASE-014` or `CASE-006`) from the Case Selector.
2. **Review Trigger Context**: View flagged transaction details, transaction amount, merchant channel, and upstream risk scores.
3. **Execute Live Investigation**: Click **Start Live Investigation** to trigger agent traversal.
4. **Inspect Graph Topology**: Use the interactive canvas to inspect nodes (Customer, Card, Transaction, DeviceProfile) and identify sharing links.
5. **Resolve Uncertainty**: If the case pauses at `MORE_EVIDENCE_REQUIRED`, navigate to the Uncertainty tab, review expected information value, and submit cardholder verification.
6. **Authorize Policy Actions**: Review recommended Next Best Actions. If an action requires L1 or L2 authorization, submit an approval or rejection.
7. **Verify Case Memory**: Inspect the generated SAR narrative and verify that the `InvestigationCase` vertex has been persisted to the graph database.

---

## 15. Testing & Validation

### Automated Test Suite

Run the full pytest suite (278 passed, 9 skipped):

```bash
pytest
```

The test suite covers:
- **Unit Tests**: Bayesian Noisy-OR mathematics, pattern detectors, evidence provenance invariants, policy rule evaluations (§3 R1–R11), Pydantic validation contracts, and demo-mode protections (answer cache, per-IP hourly limiter, daily cap).
- **Integration Tests**: FastAPI endpoint integration, SQLite idempotency, audit event logging, human-in-the-loop approval state transitions, and all 4 Nemotron roles against mocked Token Factory responses (valid/invalid JSON, unknown evidence ids, timeout fallback, prompt-injection rejection, propose/decide override).
- **Graph Backends**: Query router consistency across both SQLite and TigerGraph adapters.

CI note: `tests/conftest.py` clears `NEBIUS_API_KEY` so the suite always
runs offline against mocked responses — no API calls in CI ever.

### Live Token Factory check (maintainer-invoked)

```bash
python scripts/smoke_nemotron.py          # one real call per role, needs NEBIUS_API_KEY
python scripts/eval_heldout.py            # full held-out eval incl. plain-LLM ablation
```

### Structural Checkpoint Verification

To verify that all 20 benchmark investigation cases adhere to strict structural contracts:

```bash
python -m backend.evaluation.validate_answers
```

This validates 30 discrete checkpoints per case (600 total checkpoints) covering schema integrity, evidence citation consistency, SAR justification, and graph persistence.

---

## 16. Security Considerations

- **Credential Management**: All secrets (TigerGraph tokens, database credentials, API keys) are managed through environment variables. No secrets are committed to version control.
- **Fail-Closed Graph Mode**: In production environments, `STRICT_GRAPH_BACKEND=1` prevents silent data fabrication if the graph database encounters connectivity issues.
- **Human Authority Gating**: Critical financial actions (e.g., card blocks above policy exposure limits, filing regulatory reports) cannot auto-execute without explicit human approval recorded in the audit trail.
- **Audit Immutability**: All decisions, approver identities, timestamps, and evidence states are appended to an immutable SQLite audit log.
- **Synthetic Data Labeling**: Simulated responses in automated benchmark runs are explicitly stamped with `origin="simulated"` to maintain transparency.

---

## 17. Configuration Options

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Operating profile: `development`, `benchmark`, `production` |
| `GRAPH_BACKEND` | `local` | Graph engine: `local` (SQLite store) or `tigergraph` (Savanna Cloud) |
| `STRICT_GRAPH_BACKEND` | `false` | When true, graph query errors raise exceptions rather than falling back |
| `TG_HOST` | `""` | Base URL for the TigerGraph Savanna Cloud cluster |
| `TG_GRAPH` | `fraud_investigation` | Name of target graph in TigerGraph |
| `TG_SECRET` | `""` | TigerGraph secret for REST API authentication |
| `TG_TOKEN` | `""` | Pre-generated TigerGraph auth token |
| `EVIDENCE_REQUEST_MODE` | `simulated` | `simulated` (automated benchmark) or `human_in_loop` (interactive UI pauses) |
| `MIN_EVIDENCE_INFO_VALUE`| `0.25` | Minimum expected information gain required to halt for evidence |
| `MAX_INVESTIGATION_STEPS`| `25` | Circuit breaker for agent tool traversal depth |
| `MAX_EVIDENCE_REQUESTS` | `3` | Maximum number of evidence inquiries per case |
| `FRAUD_PROB_STOP_HIGH` | `0.85` | High-confidence fraud threshold for early stopping |
| `FRAUD_PROB_STOP_LOW` | `0.15` | High-confidence legitimate threshold for early stopping |
| `LLM_PROVIDER` | `none` | Legacy narrative formatter (`anthropic`/`openai`/`groq`/`none`); the Nemotron advisory path uses the `NEBIUS_*` variables below instead |
| `NEBIUS_API_KEY` | `""` | Nebius Token Factory key; empty = demo mode with cached answers |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1` | OpenAI-compatible endpoint |
| `NEBIUS_MODEL_NANO` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Roles 1–2 tier |
| `NEBIUS_MODEL_SUPER` | `nvidia/nemotron-3-super-120b-a12b` | Mid tier (reserved for heavier classification) |
| `NEBIUS_MODEL_ULTRA` | `nvidia/Nemotron-3-Ultra-550b-a55b` | Roles 3–4 tier |
| `DEMO_MODE` | `false` locally / `1` in the container | Serve Nemotron answers from the local cache; zero credits |
| `LLM_CALLS_PER_IP_PER_HOUR` | `20` | Per-IP hourly limiter for `/ask` and re-run endpoints (429 beyond) |
| `LLM_DAILY_CALL_CAP` | `200` | Global daily cap; beyond it, requests fall back deterministically (503 notice) |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-call timeout (2 retries with backoff) |

---

## 18. Limitations

- **Synthetic evaluation labels**: the 20-case benchmark and the closed-case
  history labels are synthetic and generated by the same pipeline that
  generates the evidence ([docs/BENCHMARK.md](./docs/BENCHMARK.md) §
  "Known limitations"); the numbers measure pipeline self-consistency on
  the published pack, not real-world performance.
- **Plain-LLM ablation scope**: the no-graph baseline in the benchmark uses
  one minimal prompt; it is intentionally the "what the graph adds"
  counterfactual, not a tuned LLM alternative.
- **Human-in-the-loop pauses in benchmark**: 11 of the 20 cases pause at
  `MORE_EVIDENCE_REQUIRED` in a single benchmark pass; their Nemotron
  proposals attach when the pending evidence request is submitted (counted
  separately in the benchmark report).
- **Per-IP limiter trusts the client IP**: it keys on the FastAPI `Request`
  client host; behind a shared proxy all judges share one bucket (safe —
  the daily cap is the backstop).
- **Single-Node Application State**: The SQLite application state store (`data/app/app.db`) is optimized for single-instance or edge deployment. Distributed horizontal scaling requires migrating state to PostgreSQL.
- **Browser-Based Canvas Rendering**: The HTML5 canvas graph visualizer is optimized for subgraphs up to ~1,500 nodes. Very large fraud ring visualizations (>5,000 nodes) should utilize WebGL rendering.
- **Data provenance**: all shipped evaluation data is generated by
  `scripts/make_synthetic_data.py` (MIT-licensed, in-repo); no third-party
  dataset rows, model artifacts, or credentials are published. Earlier,
  round-provided CSVs were used only during development and were removed
  from the history (see `data/README.md`).

---

## 19. Future Improvements

- **Distributed State Store**: Migration of application state and audit trails to PostgreSQL with pgvector integration.
- **Real-Time Stream Ingestion**: Kafka / RabbitMQ consumer integration for sub-second event ingestion directly from payment gateways.
- **Enterprise SSO & RBAC**: Integration with OAuth2 / OIDC providers (Okta, Keycloak) to map corporate roles directly to L1/L2 approval tiers.
- **Graph Neural Network (GNN) Embeddings**: Native TigerGraph GNN integration to complement rule-based pattern typologies with unsupervised structural anomaly embeddings.

---

## 20. License

This project is licensed under the **MIT License** — see the [LICENSE](./LICENSE) file for complete details.

Copyright &copy; 2026 Agentic Fraud Investigation Platform Contributors. All rights reserved.
