# HHGOA'26 — Agentic Fraud Investigation

> **Task #4 — TigerGraph Agentic Fraud Investigation + Next Best Action**
>
> An evidence-driven, uncertainty-aware, policy-governed fraud investigation platform built around TigerGraph GraphRAG.
>
> Built by **Team @BALLERINA** &bull; &copy; 2026 @BALLERINA. All rights reserved.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TigerGraph](https://img.shields.io/badge/TigerGraph-Savanna%20Cloud-F36C21)](https://www.tigergraph.com/)
[![Tests](https://img.shields.io/badge/tests-257%20passed%20(228%20base%20%2B%2029%20agentic)-2E7D32)](./docs/TECHNICAL_VALIDATION.md)
[![IEEE Checkpoints](https://img.shields.io/badge/IEEE%20checkpoints-600%2F600-2E7D32)](./artifacts/benchmark/benchmark_report.md)
[![Team](https://img.shields.io/badge/team-%40BALLERINA-C79A32)](https://github.com/shaikmohammedyasin-create/HHGoa26-Agentic-Fraud-Investigation)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/status-demo%20ready-0B5A3C)](./docs/DEMO.md)

---

## Overview

Fraud alerts are only the starting point of an investigation. A risk score alone does not explain **why** a transaction is suspicious, what entities are connected to it, whether the available evidence is sufficient, or what action should be taken under institutional policy.

HHGOA'26 turns a fraud alert into an auditable investigation:

**Alert → Graph Evidence → Pattern Reasoning → Risk → Uncertainty → Reassessment → Governed NBA → Approval → Case Memory**

The system combines:

- TigerGraph multi-hop graph traversal
- GraphRAG-style evidence retrieval
- adaptive, planner-driven tool selection
- provenance-aware evidence
- explainable Noisy-OR risk scoring
- information-value-based evidence requests
- uncertainty and reassessment
- policy-governed Next Best Actions
- human approval routing
- persistent investigation memory in TigerGraph
- an analyst command center for live investigation

---

## What Makes It Agentic

The investigation is not a fixed list of queries.

The planner chooses additional tools based on **open evidence gaps and the current case state**.

A simplified flow:

```
Trigger
  ↓
Planner
  ↓
Baseline Graph Retrieval
  ↓
Evidence + Risk Assessment
  ↓
Identify Evidence Gaps
  ↓
Planner selects next tool(s)
  ↓
Additional GraphRAG / GSQL Retrieval
  ↓
Uncertainty Check
  ↓
High-value Evidence Request
  ↓
Reassessment
  ↓
Policy-Governed NBA
  ↓
Approval / Execution
  ↓
InvestigationCase Memory
```

Each investigation records its plan trace so the selected tools and their rationale are auditable.

---

## Core Capabilities

### 1. Live TigerGraph Investigation

The system can operate against the `fraud_investigation` graph in TigerGraph Savanna Cloud.

Graph retrieval includes capabilities such as:

- transaction history
- card amount statistics
- device neighbors
- device fraud-ring analysis
- transaction identity
- online velocity / burst detection
- historical closed cases
- previous agent investigations
- pattern and case-note retrieval

The project supports strict graph operation so an unavailable authoritative graph backend does not silently become fabricated data.

### 2. Evidence-First Reasoning

Every evidence item receives an immutable evidence ID and a claim classification:

- **OBSERVED FACT** — directly retrieved graph/application fact
- **DERIVED INFERENCE** — algorithmic conclusion derived from observed data
- **MODEL SCORE** — upstream risk-model input

Evidence retains its originating query/reference so an analyst can trace a conclusion back to its source.

### 3. Explainable Risk

Fraud probability is decomposed into interpretable channels rather than presented as an unexplained number.

Relevant channels can include:

- transaction velocity
- network/card linkage
- device anomaly
- geolocation discrepancy
- fraud-ring membership
- prior agent investigation memory
- additional evidence outcomes
- historical clearing signals

### 4. Uncertainty + Evidence Loop

When the available evidence does not justify a confident decision, the system evaluates candidate evidence requests.

The evidence-gap engine estimates **expected decision impact** and suppresses requests that cannot materially change the resulting action set.

Supported modes:

- `simulated` — deterministic synthetic evidence for benchmark/demo execution, explicitly labelled as simulated
- `human_in_loop` — pauses the investigation and waits for real evidence through the API/UI

After new evidence arrives, the investigation is reassessed and the probability, uncertainty state and recommended actions can change.

### 5. Governed Next Best Action

The agent recommends actions, but the policy engine independently determines whether those actions are permitted.

```
Agent Recommendation
        ↓
Policy Engine
        ↓
Permission Tier
        ↓
Human Approval (when required)
        ↓
Action Execution
```

Permission tiers include:

- **auto** — low-impact actions
- **L1** — analyst/team-lead approval
- **L2** — fraud-manager/compliance approval

Approval decisions are revalidated against policy before execution and recorded as audit events.

### 6. Persistent Case Memory

Completed investigations are persisted as `InvestigationCase` vertices in TigerGraph and linked to relevant entities including:

- Customer
- Card
- Transaction
- Device Profile

Future investigations can retrieve prior agent cases and use that information as part of the current risk assessment.

This closes the memory loop:

**investigate → persist → retrieve → influence future investigation**

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Analyst Command Center                    │
│  Case Selector • Investigation Story • Graph • Evidence     │
│  Risk • Uncertainty • NBA • Case Memory • Benchmark         │
└─────────────────────────────┬────────────────────────────────┘
                              │ REST
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                       FastAPI Gateway                         │
│  Cases • Investigations • Graph • Evidence • Approvals      │
│  Benchmark • Health                                          │
└─────────────────────────────┬────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                 Agentic Investigation Engine                 │
│                                                              │
│ Trigger → Planner → Retrieval → Evidence → Pattern → Risk   │
│                         ↓                                    │
│             Uncertainty / Evidence Gap                       │
│                         ↓                                    │
│                Reassessment → NBA → Policy                   │
│                         ↓                                    │
│                 Approval / Execution                          │
│                         ↓                                    │
│                   Graph Memory                                │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
                ▼                              ▼
┌──────────────────────────┐      ┌───────────────────────────┐
│ TigerGraph Savanna Cloud │      │ SQLite Application State  │
│ fraud_investigation      │      │ timelines / approvals /   │
│ graph + case memory      │      │ audit metadata            │
└──────────────────────────┘      └───────────────────────────┘
```

### Technology

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Pydantic |
| Graph | TigerGraph Savanna Cloud |
| Graph access | pyTigerGraph, GSQL, optional TigerGraph MCP |
| Local state | SQLite / aiosqlite |
| Frontend | HTML, CSS, JavaScript |
| Graph UI | HTML5 Canvas |
| Testing | pytest, pytest-asyncio |
| Optional LLM | Anthropic / OpenAI |
| Logging | structlog |

---

## Repository Structure

```
.
├── backend/
│   ├── agents/             # planner + investigation orchestration
│   ├── graph/              # TigerGraph adapters and graph access
│   ├── models/             # API/domain/evidence/NBA models
│   ├── policies/            # deterministic fraud policy engine
│   ├── risk/               # risk channels and pattern reasoning
│   └── main.py             # FastAPI application
│
├── frontend/
│   ├── index.html           # analyst command center
│   ├── css/style.css        # application styling
│   └── js/
│       ├── api.js           # REST client
│       ├── app.js           # application state/UI
│       └── graph.js         # interactive graph renderer
│
├── tigergraph/              # graph schema / GSQL assets
├── cases/                   # benchmark case definitions
├── tests/                   # automated test suite
├── docs/                    # architecture, demo and validation docs
├── artifacts/               # benchmark and audit artifacts
├── scripts/                 # utility/setup scripts
├── case_pack.csv            # benchmark case pack
├── .env.example             # configuration template
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Requirements

- Python **3.11+**
- TigerGraph Savanna Cloud for live graph mode
- Git
- A modern browser such as Chrome, Edge or Brave

An LLM provider is **optional**. The application supports deterministic/template fallbacks for supported narrative functionality.

---

## Installation

### 1. Clone

```bash
git clone https://github.com/shaikmohammedyasin-create/HHGoa26-Agentic-Fraud-Investigation.git
cd HHGoa26-Agentic-Fraud-Investigation
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

Windows:

```powershell
copy .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Configure the required graph settings.

For live TigerGraph mode:

```env
GRAPH_BACKEND=tigergraph
TG_HOST=...
TG_GRAPH=fraud_investigation
TG_USERNAME=...
TG_PASSWORD=...
TG_SECRET=...
TG_PROTOCOL=https
TG_PORT=443
```

Use the authentication method required by your TigerGraph deployment. **Never commit `.env` or credentials.**

---

## Run

From the repository root:

```bash
uvicorn backend.main:app --port 8000
```

Development mode:

```bash
uvicorn backend.main:app --reload --port 8000
```

Open:

**http://localhost:8000**

---

## Demo Flow

1. Confirm TigerGraph Savanna is running.
2. Start the FastAPI server.
3. Open the Command Center.
4. Select a benchmark case.
5. Click **Start Live Investigation**.
6. Observe the investigation stages.
7. Inspect the TigerGraph topology.
8. Review evidence and provenance.
9. Review risk decomposition.
10. If the case requests evidence, provide it in `human_in_loop` mode.
11. Review reassessment and NBA changes.
12. Review policy/approval routing.
13. Inspect persisted case memory and benchmark results.

See [docs/DEMO.md](./docs/DEMO.md) for the complete judge walkthrough.

---

## Configuration

The full configuration template is in [`.env.example`](./.env.example).

### Graph backend

```env
GRAPH_BACKEND=local
```

or:

```env
GRAPH_BACKEND=tigergraph
```

### Evidence mode

```env
EVIDENCE_REQUEST_MODE=simulated
```

For a human-in-the-loop demonstration:

```env
EVIDENCE_REQUEST_MODE=human_in_loop
```

### Important limits

The environment template also controls:

- maximum investigation steps
- maximum evidence requests
- stopping thresholds
- evidence information-value threshold
- maximum reassessment rounds
- LLM provider/model settings
- local data paths

---

## API Surface

The frontend uses REST endpoints including:

| Endpoint | Purpose |
|---|---|
| `GET /health` | service/dependency health |
| `GET /api/cases` | available cases |
| `GET /api/investigations/{case_id}/full` | complete investigation state |
| `GET /api/investigations/{case_id}/graph` | investigation graph |
| `GET /investigations/{case_id}/timeline` | investigation timeline |
| `POST /investigations/{case_id}/run` | execute investigation |
| `GET /investigations/{case_id}/approvals` | approval records |
| `POST /investigations/{case_id}/approvals/{approval_id}` | approve/reject action |
| `POST /investigations/{case_id}/evidence` | submit human evidence |
| `GET /benchmark/report` | benchmark report |
| `GET /benchmark/checkpoints` | checkpoint validation |

The backend source is the authoritative API contract.

---

## Benchmark Validation

The repository contains a 20-case live TigerGraph benchmark report.

Reported results in [`artifacts/benchmark/benchmark_report.md`](./artifacts/benchmark/benchmark_report.md):

| Metric | Result |
|---|---:|
| Pipeline completion | 20 / 20 |
| Verdict accuracy | 19 / 20 — 95% |
| Primary pattern match | 18 / 20 — 90% |
| Pattern candidate recall | 18 / 20 — 90% |
| SAR determination accuracy | 18 / 20 — 90% |
| NBA accuracy | 15 / 20 — 75% |
| Graph persistence | 20 / 20 — 100% |
| IEEE checkpoints | 600 / 600 — 100% |

These are **repository-reported benchmark results** from the documented benchmark run. They are not guarantees for unseen production data.

---

## Testing

Run the full automated test suite:

```bash
pytest
```

### Test Suite Structure (228 Baseline + 29 Agentic Upgrades = 257 Total)

The test suite consists of **257 automated tests** (100% passing across unit and integration suites):

| Test Suite Component | Test Count | Description & Scope |
|---|:---:|---|
| **Core Baseline Regression** | **228** | Verified baseline test suite covering multi-hop TigerGraph queries, GraphRAG prompt context, Noisy-OR composite risk scoring (14 channels), policy engine rules (R1–R10), approval routing (`auto`/`L1`/`L2`), identity provenance, and models. *(Documented in early baseline audit reports).* |
| **Agentic Upgrades** | **+29** | Integration tests in `tests/integration/test_agentic_upgrades.py` validating the adaptive hybrid planner, expected information-value calculation, human-in-the-loop pause/resume flow, and fraud-ring graph analytics. |
| **Total Test Suite** | **257 / 257** | **100% Passed** with zero test failures across the complete system. |

- **257 / 257 automated tests passed** (100%)
- **600 / 600 IEEE checkpoints verified** (100%)
- **20 / 20 benchmark cases completed** (100%)

Run the suite again against your current checkout before treating these numbers as current execution results.

---

## Security & Fail-Closed Behavior

The system is designed around evidence grounding and explicit governance.

Key safeguards:

- credentials supplied through environment variables
- no secrets intended in source code
- strict graph operation when configured
- evidence provenance
- deterministic policy enforcement
- approval re-validation
- audit events for approval/execution
- simulated evidence explicitly labelled as simulated

Before deployment, review authentication, CORS, infrastructure permissions and TigerGraph access policies for your environment.

---

## Design

The Analyst Command Center uses a restrained Hacker House Goa-inspired visual identity:

- deep forest green
- warm beige / cream
- muted semantic colors
- editorial typography
- investigation-focused information hierarchy
- human-readable graph visualization

The graph is designed to make relationships between transactions, customers, cards, devices and previous cases understandable without requiring the analyst to decode raw graph schema names.

---

## Documentation

- [Architecture](./docs/ARCHITECTURE.md)
- [Live Demo Walkthrough](./docs/DEMO.md)
- [Technical Validation](./docs/TECHNICAL_VALIDATION.md)
- [Benchmark Report](./artifacts/benchmark/benchmark_report.md)
- [Environment Template](./.env.example)

---

## Project Status

**Demo / competition submission build**

The repository contains an end-to-end investigation pipeline with live TigerGraph integration, an analyst command center, benchmark artifacts, automated tests and policy/approval controls.

For competition/demo execution, follow the documented environment and live TigerGraph configuration.

---

## Team & Attribution

- **Team Name:** `@BALLERINA` (Team Ballerina)
- **Copyright:** &copy; 2026 `@BALLERINA`. All rights reserved.
- **Competition:** TigerGraph × Hacker House Goa 2026 (HHGOA'26)
- **Track:** Task #4 — TigerGraph Agentic Fraud Investigation + Next Best Action
- **Dataset:** Vesta Corporation / IEEE-CIS Fraud Detection Dataset

---

## License

This project is licensed under the MIT License — see the [LICENSE](./LICENSE) file for details.

&copy; 2026 `@BALLERINA` (Team Ballerina). All rights reserved. Built for Hacker House Goa 2026 Task #4.
