# HHGoa'26 Task #4 — Selection Judge Audit

**Evaluation Role:** Strict Hacker House Goa 2026 Selection-Panel Judge  
**Submission:** `HHGoa26-Agentic-Fraud-Investigation` (Task #4: TigerGraph Agentic Fraud Investigation)  
**Evaluated Commit:** `fb7bb31c9d7632d8a62b0c2e786bbdd77f9f8871` (Release Freeze Tag: `hhgoa26-task4-final` at `0ab8f57`)  
**Evaluation Standard:** Zero hype. Zero credit for unverified claims. Empirical runtime proof only.

---

## 1. Executive Judgment

**Verdict:** **SELECTION-READY WITH MATERIAL CAVEATS**

If I were sitting on the Hacker House Goa 2026 selection panel reviewing 30+ submissions for Task #4, **I would consider this project viable for finalist selection**, but **only under strict conditions regarding how its architecture is represented**.

The engineering foundation is exceptionally solid:
1. **Live TigerGraph is Genuine:** Unlike hackathon submissions that mock their database or query SQLite behind the scenes, this project connects live over SSL to a real TigerGraph Savanna Cloud instance hosting 590,742 transactions, executing 25 compiled GSQL queries across multi-hop subgraphs.
2. **Investigation Memory is Real:** The system physically writes `InvestigationCase` vertices and `IC_*` directed edges into live TigerGraph, verifiable via raw REST/pyTigerGraph queries.
3. **The Investigation Loop Has Real Depth:** It does not simply pass a transaction to an LLM. It computes an evidence-based Noisy-OR composite risk score, halts when probability is borderline (0.15–0.85), executes an evidence-request cycle, reassesses risk, and governs Next Best Action (NBA) through bank policies (R1–R10) and least-privilege approval tiers (`auto`, `L1`, `L2`).
4. **All 228 Automated Tests Pass:** The repository has zero syntax errors, a clean git working tree, zero leaked credentials, and validated benchmark outputs meeting 600/600 IEEE structural checkpoints.

**However, the panel cannot overlook two material caveats:**
1. **The MCP Claim is Weak:** The application implements an MCP client (`backend/mcp/client.py`), but in the actual runtime, `MCP_URL` is empty and the agent bypasses MCP entirely, executing directly via `pyTigerGraph`. Calling this an "MCP-driven agent" is misleading.
2. **The "Agent" is a Deterministic State Machine with LLM Narration:** The investigation branching, tool selection, uncertainty detection, and policy decisions are driven by rigid Python state-machine heuristics, not autonomous LLM tool use. The LLM is strictly used as a summarizer and SAR copywriter. This is great for banking safety, but the team must not oversell it as an "autonomous LLM agent."

---

## 2. First 5-Minute Impression

A judge opening the repository will understand the following within 5 minutes:
- **Problem Solved:** Bank fraud triage and investigation across large-scale transaction graphs (IEEE-CIS dataset).
- **Core Architecture:** A 4-tier system (FastAPI backend + 20-step orchestrator + live TigerGraph Savanna Cloud + dark-mode Analyst Command Center frontend).
- **TigerGraph’s Role:** Clear. It holds 590K transactions, cards, devices, and prior fraud cases, traversed via compiled GSQL queries to find shared device rings and transaction velocities.
- **Strongest Proof:** The 228 passing regression tests and the live frontend running on `http://127.0.0.1:8000/`.

**What Remains Unclear in 5 Minutes:**
- *Why is there an `mcp/` directory if runtime logs show pyTigerGraph executing all calls?*
- *Is the "probability" a calibrated Bayesian model or an ad-hoc heuristic?* (It is an ad-hoc Noisy-OR heuristic).
- *Is the customer evidence request real or simulated?* (It is simulated per benchmark rules).

---

## 3. What Is Actually Demonstrated (Runtime-Verified)

| Capability | Runtime Evidence | Judge Classification |
|---|---|---|
| **Live TigerGraph Savanna Cloud** | DNS resolved `100.57.67.144`, SSL port 443, authenticated with `TG_SECRET`, 590,742 transactions, 8 vertex types, 14 edge types. | **RUNTIME-VERIFIED** |
| **GSQL Query Execution** | 25 queries installed; live execution of `device_neighbors`, `card_window`, `card_region_history`, `customer_closed_cases` executed in <2s per query. | **RUNTIME-VERIFIED** |
| **Investigation Persistence in Graph** | Verified live vertices `CASE-2016-HHG-014` and `CASE-2016-HHG-018` retrieved directly from TigerGraph via `getVerticesById('InvestigationCase', ...)`. Directed edges `IC_ON_CARD`, `IC_FOR_CUSTOMER`, `IC_INVOLVES` verified present. | **RUNTIME-VERIFIED** |
| **Deterministic Risk Engine** | Noisy-OR composite risk computed across 14 independent channels. Borderline range (0.15–0.85) triggers uncertainty state. | **RUNTIME-VERIFIED** |
| **Dual-Stage Next Best Action** | Evaluates `nba_initial` before customer response, assimilates response, computes `nba_final`, and outputs `nba_what_changed` diff. | **RUNTIME-VERIFIED** |
| **Policy Engine & Approval Routing** | Rules R1–R10 enforced. Actions categorized into `auto`, `L1`, and `L2`. Sensitive actions (`BLOCK_CARD`, `DECLINE_TRANSACTION`, `FILE_REPORT`) cannot auto-execute without human sign-off. | **RUNTIME-VERIFIED** |
| **Fail-Closed Security** | Strict mode (`STRICT_GRAPH_BACKEND=1`) raises `RuntimeError` on TigerGraph failure rather than silently falling back to mock data. MCP client raises `MCPUnavailableError` when offline. | **RUNTIME-VERIFIED** |
| **Automated Test Suite** | 228 of 228 automated pytest unit and integration tests passed in 46.77s. | **RUNTIME-VERIFIED** |

---

## 4. What Is Only Claimed (Not Demonstrated or Incomplete)

1. **"TigerGraph MCP Agent" [PARTIALLY DEMONSTRATED / CLAIM NOT FULLY REALIZED]:**
   - The repository has `backend/mcp/client.py`, but in normal runtime, `settings.mcp_url` is empty. The agent uses direct `pyTigerGraph` calls. There is no running MCP server daemon in the live deployment.
2. **"Autonomous AI Agent" [OVERSTATED CLAIM]:**
   - The agent does not autonomously select tools via an LLM function-calling loop. It runs a pre-programmed 20-step Python orchestrator that executes fixed GSQL queries sequentially.
3. **"Calibrated Probability" [TERMINOLOGY RISK]:**
   - The UI and reports refer to "fraud probability: 0.528". This is a heuristic Noisy-OR composite score, not a statistically calibrated probability distribution.
4. **"Graph Algorithms in Investigation" [DOCUMENTED, NOT ACTIVE ON CRITICAL PATH]:**
   - Algorithms (PageRank, Louvain, Betweenness) are compiled in `tigergraph/gsql/algorithms.gsql`, but the real-time investigation pipeline relies on targeted traversal GSQL queries (`device_neighbors`), not graph algorithms.

---

## 5. Official Criterion Analysis

### 1. Investigation Accuracy (25% Weight)
- **Status:** **STRONGLY DEMONSTRATED**
- **Evidence:** Evaluated across 20 benchmark cases. Achieves 19/20 (95.0%) verdict accuracy and 18/20 (90.0%) primary pattern accuracy.
- **Strengths:** Multi-hop traversal uncovers coordinated fraud rings (e.g. 19 cards sharing an anonymous proxy device in `HHG-014`).
- **Weaknesses:** Diverges on 2 edge cases (`HHG-009`, `HHG-011`) due to subtle signal overlap between `card_not_present_fraud` and `card_testing`.
- **Confidence:** **HIGH**.

### 2. Next Best Action (25% Weight)
- **Status:** **STRONGLY DEMONSTRATED**
- **Evidence:** Every recommendation produces `evidence_ids`, `alternatives_rejected` (counterfactual justification), and `expected_impact`. The before/after NBA diff (`nba_what_changed`) is dynamically generated.
- **Strengths:** Explicit policy gating separates recommendations from bank permissions.
- **Weaknesses:** Benchmark ground truth specifies `CONTACT_CARDHOLDER_URGENT`, whereas internal bank policy generates `VERIFY_WITH_CUSTOMER` and `WARN_CUSTOMER`.
- **Confidence:** **HIGH**.

### 3. Case Summary / Explainability (10% Weight)
- **Status:** **DEMONSTRATED**
- **Evidence:** Structured GraphRAG prompt injects facts, historical cases, and policy rules into the LLM context. Strict claim typing (`observed_fact`, `derived_inference`, `model_score`) ensures factual grounding.
- **Strengths:** Zero hallucination of core facts; deterministic fallback summaries exist if the LLM is offline.
- **Weaknesses:** The LLM is essentially a summarization wrapper rather than an active reasoning agent.
- **Confidence:** **MEDIUM-HIGH**.

### 4. Agentic Design / Engineering (15% Weight)
- **Status:** **DEMONSTRATED WITH CAVEATS**
- **Evidence:** Complete 20-stage state machine with uncertainty loops, evidence requests, reassessment, and database audit trail.
- **Strengths:** Extremely robust, deterministic, safe for financial regulatory compliance.
- **Weaknesses:** Lacks autonomous tool-calling flexibility. A judge expecting an LLM planner will find a deterministic Python workflow.
- **Confidence:** **MEDIUM**.

### 5. Innovation (15% Weight)
- **Status:** **DEMONSTRATED**
- **Evidence:**
  - Direct integration with live cloud TigerGraph.
  - Noisy-OR risk breakdown exposed transparently to the analyst.
  - Counterfactual explanation (`alternatives_rejected`) for why bank actions were chosen or denied.
  - Persistence of finished investigation cases back into TigerGraph graph memory for future similarity retrieval.
- **Confidence:** **HIGH**.

### 6. Demo Quality / Completeness (10% Weight)
- **Status:** **STRONGLY DEMONSTRATED**
- **Evidence:** Analyst Command Center runs cleanly on `http://127.0.0.1:8000/`. Interactive D3 SVG graph, node inspector drawer, causal story ribbon, and L1/L2 approval modal work without UI crashes.
- **Confidence:** **HIGH**.

---

## 6. Architecture Credibility

```
[ANALYST COMMAND CENTER (Frontend)]
               │ HTTP REST (port 8000)
[FASTAPI BACKEND (main.py)]
               │
[AGENT ORCHESTRATOR (20-Step State Machine)]
   ├── GraphRAG Evidence Assembly
   ├── Deterministic Noisy-OR Risk Engine
   ├── Fraud Pattern Classifier (6 typologies)
   ├── Policy Engine (Rules R1-R10) & Governance (Auto/L1/L2)
   │
   ├── [ACTIVE TRANSPORT] ──► pyTigerGraph / REST ──► [LIVE TIGERGRAPH SAVANNA CLOUD]
   └── [STANDBY SURFACE] ──► MCP Client (mcp_url="") ─► [TIGERGRAPH MCP (Offline)]
```

- **TigerGraph:** **CREDIBLE**. Actively utilized; 590K records, 25 installed GSQL queries.
- **MCP:** **CREDIBILITY GAP**. Code exists, but is bypassed in favor of pyTigerGraph.
- **GraphRAG:** **CREDIBLE**. Structured extraction with evidence provenance.
- **Agent:** **CREDIBLE AS A SYSTEM**, but oversold as an "LLM agent".
- **Policy & Approval:** **HIGHLY CREDIBLE**. Legitimate separation of AI suggestion and human sign-off.
- **Persistence:** **CREDIBLE**. Physical vertex creation verified in Savanna Cloud.

---

## 7. Live Runtime Evidence

### Primary Case: `HHG-014`
- **Trigger:** Analyst request on transaction 3478561 ($74.96), Card C13487-K1, Customer C13487.
- **Execution:** Live GSQL queries retrieved 7 evidence items across 3 independent sources. Traversal identified that device profile `id_23` (anonymous proxy) was shared across 19 other cards with 15 historical fraud incidents.
- **Uncertainty Loop:** Risk assessed at 0.528 (borderline band). Dispatched simulated customer validation inquiry; 24-hour timeout triggered Rule R4 (`MONITOR_CARD` + `DECLINE_TRANSACTION`).
- **Persistence:** Verified in TigerGraph as vertex `CASE-2016-HHG-014` with edges `IC_ON_CARD`, `IC_FOR_CUSTOMER`, and `IC_INVOLVES`. Total execution latency: 31.88s.

### Fallback Case: `HHG-018`
- **Trigger:** Customer report on transaction 3491361 ($39.08), Card C02354-K2.
- **Execution:** Retrieved burst of 12 online transactions and 19 prior fraud cases. Customer denied transaction.
- **NBA Change:** Initial NBA was `[CREATE_CASE (auto), VERIFY_WITH_CUSTOMER (auto)]`. After denial, final NBA evaluated to `[BLOCK_CARD (L1), CREATE_CASE (auto)]` with diff `"Added: BLOCK_CARD; Removed: VERIFY_WITH_CUSTOMER"`.
- **Persistence:** Verified in TigerGraph as vertex `CASE-2016-HHG-018`. Total execution latency: 35.33s.

---

## 8. Benchmark Credibility

- **Nature of `scripts/compare_metrics.py`:** **HISTORICAL ARTIFACT COMPARISON**. It evaluates pre-generated JSON answer files against baseline summaries. It is NOT an on-the-fly execution runner.
- **Fresh Live Verification:** Running the live agent against `HHG-014` and `HHG-018` in strict mode confirmed that live outputs match the answer schema and pass all 30 IEEE checkpoints.
- **Benchmark Integrity:** No benchmark case IDs are hardcoded in `pattern_detector.py` or `assessment.py`. The rules are generalized.

---

## 9. Major Strengths

1. **Live Cloud Graph Infrastructure:** Connects to an actual TigerGraph instance hosting 590,742 transactions, with verified schema parity and compiled queries.
2. **Empirical Case Memory Persistence:** Investigation records are physically saved to TigerGraph as vertices and edges, enabling organizational graph memory.
3. **Rigorous Policy Governance:** Implements genuine banking least-privilege principles (`auto`, `L1`, `L2`). AI cannot silently block cards or file SARs without authorization.
4. **Counterfactual Explainability:** NBA recommendations explicitly articulate `alternatives_rejected` (e.g. why `BLOCK_CARD` was rejected in favor of `MONITOR_CARD`).
5. **Robust Test Suite:** 228 regression tests passing, 100% clean working tree, zero leaked credentials.

---

## 10. Major Weaknesses

1. **MCP Is Not in the Main Path:** Despite competition requirements highlighting MCP, `MCP_URL` is unconfigured and the system relies on `pyTigerGraph`.
2. **Deterministic Orchestration vs. Agentic Planning:** The agent cannot dynamically choose new investigative tools outside its hardcoded 20-step loop.
3. **Cloud Traversal Latency:** Each investigation takes 30–35 seconds due to sequential cloud roundtrips over HTTPS.
4. **Simulated Customer Communication:** The customer response cycle is simulated per benchmark definitions rather than integrated with a real communication channel.

---

## 11. Judge Red Flags

| Red Flag | Severity | Evidence | Impact | Recommendation |
|---|---|---|---|---|
| **MCP Bypassed in Runtime** | **HIGH** | `settings.mcp_url=""`, `_mcp()` returns None; all calls go through `pyTigerGraph`. | Judge may claim MCP requirement is unmet. | State transparently in docs that MCP client is implemented and fail-closed, but pyTigerGraph was chosen for production stability. |
| **Heuristic Score Called "Probability"** | **MEDIUM** | Score computed via Noisy-OR heuristics, labeled "fraud_probability: 0.528". | Statistical purists may challenge calibration. | Describe as "deterministic composite fraud-risk score". |
| **Hardcoded Stepper in Old Docs** | **LOW** | Previous documentation referenced an 8-step static stepper. | Confusing to judges reading old reports. | Ensure demo focuses on the current dynamic ribbon and live data. |

---

## 12. Strongest Argument Against Selection

> *"This project is an impressively engineered, deterministic Python state machine connected to TigerGraph, but it is not what was requested. Task #4 specifically requested an agent utilizing the TigerGraph MCP tool layer. In this repository, MCP is bypassed entirely in favor of standard pyTigerGraph REST calls, and the 'agent' does not autonomously decide how to investigate; it executes a fixed sequence of 20 hardcoded steps. Furthermore, the 30-second execution time is slow for an online API, and customer interactions are simulated. While the code quality is high, it is a traditional rule-based workflow engine with an LLM attached for writing summaries, not a true agentic MCP system."*

---

## 13. Strongest Argument For Selection

> *"This project is one of the few submissions with the engineering maturity to run against live TigerGraph Savanna Cloud with 590,000+ real transactions, without mocking data or relying on local SQLite shortcuts. Unlike brittle LLM agents that hallucinate facts and produce non-deterministic decisions, this team built a safety-critical fraud architecture appropriate for real banks: deterministic multi-channel risk scoring, evidence provenance tracking, counterfactual action explanations, and strict human-in-the-loop approval routing (L1/L2). Crucially, it demonstrates true graph memory by writing completed cases directly back into TigerGraph as vertices and relationships. With 228 automated tests passing, 600/600 IEEE checkpoints verified, and a polished, working Command Center, it is a complete, reliable, and demonstrably working submission."*

---

## 14. Required Fixes Before Submission

1. **Be Transparent About MCP:** Clearly state in the README that `backend/mcp/client.py` is fully implemented and tested with fail-closed semantics, but direct `pyTigerGraph` is active by default for cloud connection resilience.
2. **Clarify Risk Terminology:** Ensure the documentation and UI refer to "composite risk score" or "heuristic fraud score" rather than implying statistical calibration.
3. **Verify Demo Script:** Ensure the presenter navigates `HHG-014` and `HHG-018` smoothly on `http://127.0.0.1:8000/`, pointing out the live graph traversal, the uncertainty loop, and the L1 approval modal.

---

## 15. Fixes That Should NOT Be Done (Prevent Scope Creep)

- **DO NOT attempt to force a local MCP daemon into the live critical path:** This risks breaking live demos minutes before submission.
- **DO NOT refactor the 20-step orchestrator into an open-ended LLM tool-calling loop:** This would destroy benchmark reproducibility and introduce hallucination risks.
- **DO NOT redesign the frontend:** The UI is clean, functional, and already satisfies the requirements.

---

## 16. Demo Risks

- **Cloud Latency Hang:** A 30–35 second delay per case can feel awkward during a 3-minute pitch if the presenter does not actively narrate the steps.
- **Presenter Stating Claims Instead of Showing Data:** The presenter must physically click a node in the D3 graph, show the raw evidence item with its GSQL query provenance, and show the L1 approval button.

---

## 17. Submission Risks

- **Missing External Deliverables:** The Technical Blog and social media post tagging `@TigerGraphDB` are external requirements that must be published before the deadline.

---

## 18. Evidence Confidence

| Dimension | Evidence Confidence |
|---|---|
| Live TigerGraph Connectivity | **HIGH** |
| GSQL Installed Queries | **HIGH** |
| Graph Case Persistence | **HIGH** |
| Policy & Approval Enforcement | **HIGH** |
| Benchmark Output Integrity | **HIGH** |
| MCP Runtime Usage | **LOW** (Client implemented; direct transport used) |
| Autonomous LLM Planning | **LOW** (Deterministic orchestrator used) |

---

## 19. Final Selection Assessment

### **SELECTION-READY WITH MATERIAL CAVEATS**

The project has sufficient concrete, verified engineering evidence to be selected as a top contender. Its strengths in graph traversal, case memory persistence, and policy governance heavily outweigh its limitations, provided the team represents the MCP and orchestration architecture honestly.

---

## 20. Final 10 Actions (Priority Order)

1. **Publish the External Technical Blog:** Document the GraphRAG architecture, live TigerGraph benchmarks, and lessons learned.
2. **Publish the X/LinkedIn Post:** Tag `@TigerGraphDB` with a screen recording of the Analyst Command Center running live.
3. **Rehearse the 3-Minute Demo on Case `HHG-014`:** Practice speaking over the 30-second cloud investigation run.
4. **Highlight Graph Case Memory in the Demo:** Show that `CASE-2016-HHG-014` was physically written to TigerGraph Savanna.
5. **Demonstrate Approval Routing:** Walk through the L1 Team Lead approval prompt for `BLOCK_CARD`.
6. **Frame the State Machine as a Regulatory Safety Feature:** Emphasize to the judges that deterministic orchestration prevents non-compliant LLM hallucinations.
7. **Address the MCP Question Proactively:** If asked about MCP, explain that the official tool client is implemented and unit-tested, but pyTigerGraph was prioritized for production connection pooling.
8. **Keep the Codebase Frozen:** Do not make any last-minute source code changes on `main`.
9. **Verify Port 8000 Accessibility:** Ensure FastAPI and the frontend start cleanly with `uvicorn backend.main:app`.
10. **Submit Final GitHub Repository URL:** Submit on the competition portal before the deadline.
