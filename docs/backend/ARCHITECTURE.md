# Backend Architecture

TigerGraph-native, evidence-grounded, policy-controlled fraud investigation backend for HHGOA 2026.

Frontend is out of scope. This backend exposes a typed HTTP API that a later analyst UI can consume.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | Python 3.11+, FastAPI, Pydantic v2 | Typed contracts, OpenAPI for frontend handoff |
| App state | SQLite (`data/prepared/app.db`) | Durable investigation/case/audit state without a second copy of the 590k-row dataset |
| Graph | TigerGraph (Savanna/CE) when configured; local SQLite graph store otherwise | Same query interface; TigerGraph is the production investigation engine |
| Agent | Custom persisted state machine | One orchestrator, no swarm, no second framework |
| Retrieval | Keyword/BM25 over closed-case notes + policy text; TigerGraph vector search when available | Keep graph and retrieval together; no extra vector DB |
| LLM | Optional provider abstraction (Anthropic / OpenAI-compatible) | Synthesis and explanation only. Never facts, policy, or execution |

## Source of truth

1. Official challenge PDF / README in this repository
2. `transactions.csv`, `identity.csv`, `closed_cases_history.csv`, `case_pack.csv`
3. Official TigerGraph + tigergraph-mcp docs
4. This backend

## Conceptual flow

```
API
  -> Investigation Service
       -> Agent Orchestrator (persisted state machine)
            +-- Graph Service (TigerGraph or local store)
            +-- GraphRAG (graph evidence + cases + policy + patterns)
            +-- Policy / Permission / Approval
            +-- Action adapters
            +-- Case memory
            +-- Evidence layer
```

Required product loop:

```
TRIGGER -> CASE -> GRAPH INVESTIGATION -> EVIDENCE -> GraphRAG
  -> RISK / CONFIDENCE / UNCERTAINTY
  -> additional evidence (if decision-relevant)
  -> REASSESS -> NEXT-BEST-ACTION -> POLICY -> PERMISSION
  -> APPROVAL -> ACTION -> CASE MEMORY -> COMPLETE
```

## Separation of concerns

| Deterministic | LLM (optional) |
|---|---|
| Graph facts, GSQL, local queries | Tool-selection hints |
| Pattern detectors | Evidence synthesis |
| Risk / confidence heuristics | Case summary, SAR narrative |
| Policy, permission, approval, execution | Explanation text |
| State transitions, audit | — |

The LLM cannot write arbitrary GSQL, bypass policy, approve its own actions, or invent evidence.

## Datastores

| Store | Holds | Does not hold |
|---|---|---|
| TigerGraph | Customers, cards, transactions, devices, emails, regions, closed cases, investigation cases, evidence, actions | Full Vesta V1–V339 dump |
| SQLite graph mirror (`investigation.db`) | Slim investigation tables + indexes for local/dev and for when TG is down | Duplicate of unused Vesta columns |
| SQLite app (`app.db`) | Investigation state, audit events, approvals, idempotency keys | Graph topology |

When TigerGraph is unavailable the API reports `degraded`. Missing graph data is never converted into “no fraud found”.

## Package layout

```
backend/
  main.py                 FastAPI app
  config.py
  logging.py
  models/                 Pydantic contracts
  db/                     SQLite app state
  data/                   CSV prepare + indexes
  graph/                  Query port, local store, TigerGraph adapter
  mcp/                    Official TigerGraph MCP client
  evidence/
  cases/
  memory/
  policies/
  risk/
  uncertainty/
  nba/
  actions/
  approvals/
  agents/                 Orchestrator, tools, state machine
  llm/
  graphrag/
  evaluation/
  api/                    HTTP routers
tigergraph/
  schema/ loading/ gsql/ algorithms/ queries/ scripts/
tests/
  unit/ integration/ e2e/
evaluation/               Benchmark runner outputs live in cases/
```

## Runtime modes

| Mode | Graph | LLM | Use |
|---|---|---|---|
| `development` | Local store from prepared SQLite | Optional | Tests, demo |
| `benchmark` | Local store or TigerGraph | Optional | 20 case pack files |
| `production` | TigerGraph required | Optional | Real workspace |

Fixtures never leak into benchmark evidence. Benchmark cases use the same orchestrator as live investigations.
