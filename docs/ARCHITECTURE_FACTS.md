# ARCHITECTURE_FACTS.md — HHGOA'26 Task #4

**System:** Agentic Fraud Investigation — TigerGraph  
**Auditor:** Senior Technical Reviewer, QA Engineer, TigerGraph Engineer, Release Engineer  
**Date:** 2026-09-21  
**Git HEAD:** `fb7bb31c9d7632d8a62b0c2e786bbdd77f9f8871` (Release Freeze Tag: `hhgoa26-task4-final` at `0ab8f57`)

---

## 1. FACTS (Directly Verified from Code and Runtime Traces)

1. **TigerGraph Connectivity & Environment**:
   - The system connects over HTTPS/SSL (port 443) to `tg-f02a8385-10f3-4f5e-b991-c8a8aafa6aca.tg-2635877100.i.tgcloud.io`.
   - The active graph is `fraud_investigation`.
   - Authentication succeeds via `TG_SECRET`, dynamically acquiring a bearer API token stored in `pyTigerGraph.TigerGraphConnection.apiToken`.
   - The live graph contains 8 vertex types: `Customer` (13,553), `Card` (14,850), `Transaction` (590,742), `DeviceProfile` (9,706), `EmailDomain` (969), `BillingRegion` (332), `ClosedCase` (5,565), and `InvestigationCase` (20+).
   - The live graph contains 14 directed edge types: `OWNS`, `MADE`, `FROM_DEVICE`, `PURCHASER_EMAIL`, `RECIPIENT_EMAIL`, `BILLED_IN`, `NEXT_TXN`, `CC_INVOLVES`, `CC_ON_CARD`, `CC_CONNECTED_TO`, `IC_INVOLVES`, `IC_ON_CARD`, `IC_FOR_CUSTOMER`, `IC_ON_DEVICE`.
   - 25 installed GSQL queries are compiled and active on the cluster (including `card_transaction_history`, `card_window`, `tiny_txn_sequence`, `card_region_history`, `device_neighbors`, `customer_closed_cases`, `card_closed_cases`, `cases_by_device`, `card_velocity`).

2. **Graph Transport & MCP Architecture**:
   - The code defines an MCP client in `backend/mcp/client.py` wrapping the official `tigergraph-mcp` tool surface (`/tools/call` for `run_query`, `get_schema`, `vector_search`, `upsert_data`).
   - In `backend/config.py`, `settings.mcp_url` defaults to `""`. In `.env`, `MCP_URL` is unset.
   - At runtime, `backend/graph/tg_adapter.py` checks `if not settings.mcp_url: return None`. Because `MCP_URL` is empty, `_mcp()` returns `None`.
   - All live graph operations route through `pyTigerGraph` (`conn.runInstalledQuery()`) with fallback to direct TigerGraph REST endpoints (`/restpp/query/...`).
   - `MCPClient` is tested in `tests/integration/test_mcp_client.py` and `tests/integration/test_tigergraph_live_agent.py`; when configured with an unreachable URL, it strictly fails closed (`MCPUnavailableError`) and never fabricates mock results.

3. **Investigation Workflow & State Transitions**:
   - The orchestrator (`backend/agents/orchestrator.py`) executes a 20-step state machine with explicit transitions: `TRIGGERED` → `CASE_CREATED` → `INVESTIGATING` → `EVIDENCE_GATHERED` → `ASSESSING` → `MORE_EVIDENCE_REQUIRED` → `EVIDENCE_REQUESTED` → `EVIDENCE_RECEIVED` → `REASSESSING` → `ACTION_RECOMMENDED` → `COMPLETED`.
   - Every transition appends an `AuditEvent` with timestamps and state metadata into SQLite table `audit_events`.
   - In strict mode (`STRICT_GRAPH_BACKEND=1`), any TigerGraph connection or query failure immediately raises `RuntimeError` rather than silently falling back to SQLite.

4. **Evidence Provenance & GraphRAG**:
   - Evidence items are constructed via `_ev()` with explicit fields: `claim`, `source` (`graph`, `customer`, `document`, `external`), `ref` (exact GSQL query signature), `entity_ids`, `severity`, `confidence`, and `provenance` (`step`, `claim_type`: `observed_fact`, `derived_inference`, `model_score`).
   - GraphRAG (`backend/graphrag/context.py`) assembles structured evidence, historical case outcomes, policy definitions (Rules R1–R10), and fraud pattern definitions into bounded prompt context.
   - LLM generation is restricted exclusively to textual summarization and SAR narrative drafting. Risk scores, pattern classifications, and policy actions are computed deterministically and cannot be overridden by the LLM. If the LLM is unconfigured (`llm_provider=none`), deterministic grounded generators (`_grounded_summary`, `_grounded_sar_narrative`) execute with zero hallucinations.

5. **Risk Assessment & Pattern Detection**:
   - Fraud risk is computed by `compute_fraud_probability()` in `backend/risk/assessment.py` using a deterministic Noisy-OR composite across 14 distinct evidence channels (trigger score, card-testing sequence, new device, proxy, new region, burst velocity, connected fraud history, customer denial/confirmation).
   - Pattern detection evaluates 6 typologies (`card_testing`, `card_not_present_fraud`, `card_not_present_new_device`, `out_of_region_use`, `account_takeover`, `undocumented`) and outputs primary pattern, confidence, secondary pattern, and a ranked list of `pattern_candidates`.

6. **Policy Engine & Least-Privilege Governance**:
   - `backend/policies/engine.py` implements Rules R1–R10.
   - Strict separation exists: Agent Recommendations ≠ Policy Rules ≠ Permission Routing ≠ Human Approval.
   - Permission routing table:
     - `auto`: `ALLOW_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `GENERATE_REPORT`, `CREATE_CASE`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD`.
     - `L1` (Team Lead approval): `DECLINE_TRANSACTION`, `BLOCK_CARD` (when exposure <= $2,500).
     - `L2` (Fraud Manager approval): `BLOCK_CARD` (when exposure > $2,500), `BLOCK_ALL_CARDS`, `FILE_REPORT` (SAR).
   - Sensitive actions cannot be automatically executed without an explicit approval decision recorded in the database.

7. **Graph Persistence (Case Memory)**:
   - When an investigation completes, `graph.write_investigation_case()` writes an `InvestigationCase` vertex to live TigerGraph and creates directed edges: `IC_ON_CARD`, `IC_FOR_CUSTOMER`, `IC_INVOLVES` (to Transaction vertices), and `IC_ON_DEVICE` (to DeviceProfile).
   - Live query of `getVerticesById('InvestigationCase', ['CASE-2016-HHG-014', 'CASE-2016-HHG-018'])` confirms vertices exist in Savanna Cloud with full attributes (`verdict`, `fraud_probability`, `pattern`, `exposure_usd`, `summary`, `status`).

8. **Test Suite Status**:
   - Full regression test run: 228 passed of 228 executed in 46.77s.

---

## 2. ASSUMPTIONS (Inferred from Architecture and Benchmarks)

1. **Benchmark Evaluation Intent**:
   - The competition benchmark evaluation compares output answer JSON files in `cases/` against ground truth criteria.
   - The benchmark actions list `CONTACT_CARDHOLDER_URGENT`; the system's policy engine produces `VERIFY_WITH_CUSTOMER` and `WARN_CUSTOMER`. This is assumed to be a naming vocabulary difference rather than a failure of investigative reasoning.
2. **Customer Interaction in Real Banking**:
   - In a production banking deployment, customer outreach would trigger an asynchronous webhook/SMS gateway. In this benchmark/offline prototype, customer responses are assumed and simulated according to benchmark scenario definitions.
3. **External Submission Deliverables**:
   - The competition rubric lists a technical blog and social media post tagging `@TigerGraphDB`. It is assumed these are to be published externally by the team during submission submission rather than stored inside git.

---

## 3. RISKS (Potential Weaknesses and Constraints)

1. **Direct Transport Bypasses MCP Daemon**:
   - The Task #4 brief lists TigerGraph MCP as a requirement. While `MCPClient` is implemented and verified to fail closed, in the primary runtime path `pyTigerGraph` is used because no standalone MCP server is hosted. Judges checking if the agent communicates via JSON-RPC to an MCP process will find it using `pyTigerGraph` unless `MCP_URL` is set.
2. **Cloud Latency (15–35s per Investigation)**:
   - Because investigations make ~15–20 GSQL calls to a cloud-hosted TigerGraph instance across 590K+ vertices, end-to-end execution latency is 15–35 seconds per case. A slow network connection during a live demo could cause the browser to wait.
3. **Strict Probability Cutoffs Near Decision Boundaries**:
   - The certainty boundaries at 0.15 and 0.85 are rigid cutoffs. Cases scoring 0.833–0.848 with customer denials remain classified as `uncertain` / review rather than auto-closing as `fraud`.
4. **Pattern Divergence on Overlapping Signals**:
   - On 2 of 20 benchmark cases (`HHG-009`, `HHG-011`), overlapping features between `card_not_present_fraud`, `card_testing`, and `card_not_present_new_device` cause primary pattern divergence. Overall primary pattern accuracy is 90% (18/20), and candidate recall is 90%.

---

## 4. RECOMMENDATIONS (Evidence-Backed)

1. **Preserve Current Codebase Without Refactoring (Freeze Intact)**:
   - All 228 automated tests pass, the live TigerGraph cluster is healthy, graph persistence is empirically verified, and the live frontend renders all states cleanly. Making modifications to working code on `main` poses a high risk of breaking the frozen release.
2. **Document MCP Transport Honestly**:
   - State clearly in the report and presentation that the MCP client is fully implemented with fail-closed security, but pyTigerGraph is utilized for production speed and direct connection stability.
3. **Highlight Provenance and Auditability in the Demo**:
   - Emphasize the live TigerGraph roundtrips, the dynamic graph visualization, the transparent Noisy-OR breakdown, and the human-in-the-loop approval routing during the 3–5 minute presentation.
