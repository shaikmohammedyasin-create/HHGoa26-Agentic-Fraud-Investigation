# HHGOA'26 Live Demo Walkthrough (3–5 Minute Script)

This guide outlines the exact demonstration sequence for judges to experience the **TigerGraph Agentic Fraud Investigation Command Center**.

---

## Prerequisites (Pre-Flight Checklist)

1. **Verify TigerGraph Savanna Status**:
   - Open [savanna.tgcloud.io](https://savanna.tgcloud.io) and ensure the workspace is in the **READY / RUNNING** state.
   - *If suspended:* Click **Resume/Start** and wait ~3 minutes for the green indicator.
2. **Launch Application Server**:
   ```bash
   .venv\Scripts\activate
   uvicorn backend.main:app --port 8000
   ```
3. **Open Command Center**:
   - Navigate to [http://localhost:8000](http://localhost:8000) in Chrome, Edge, or Brave.
   - Confirm the header badges read `TG: healthy` and `DB: healthy`.

---

## 3–5 Minute Presentation Flow

### Phase 1: Context & Immediate Orientation (0:00 – 0:45)
- **Visual**: Point out the Top Bar and Key Performance Indicators (KPIs).
- **Narrative**:
  > *"In financial fraud detection, an alert score from a machine learning model is an input, not an answer. Our agentic investigation platform uses TigerGraph GraphRAG to synthesize multi-hop relationships, explain risk transparently via Noisy-OR channel decomposition, resolve uncertainty through customer inquiry, and enforce strict bank policy governance before taking action."*
- **Highlight**:
  - Show the **Health Pill**: Proves connection to live TigerGraph Savanna in strict mode (`STRICT_GRAPH_BACKEND=1`).

---

### Phase 2: Live Investigation Demonstration (0:45 – 2:00)
- **Select Case**: From the Case Selector dropdown, select **`HHG-014`**.
- **Action**: Click the **`Start Live Investigation`** button.
- **Narrative**:
  > *"Watch the 8-stage causal story ribbon as the agent executes. It ingests the flagged transaction, initializes graph memory, runs live TigerGraph queries—including 2-hop device co-usage traversals—and synthesizes concrete evidence."*
- **Highlight**:
  - **Evidence Provenance**: Point out the **Claim Type pills**:
    - `OBSERVED FACT`: Verified graph facts (e.g., historical transaction volume, shared devices).
    - `DERIVED INFERENCE`: Graph topological patterns.
    - `MODEL SCORE`: Upstream detection model input.
  - **Filter Buttons**: Click `Observed Fact` then `All` to show dynamic evidence filtering.

---

### Phase 3: Noisy-OR Decomposition & The Evidence-Gap Loop (2:00 – 3:15)
- **Visual**: Scroll to the **Risk Analysis** (Noisy-OR decomposition card) and **Uncertainty Loop** cards.
- **Narrative**:
  > *"Rather than outputting a black-box score, our engine decomposes fraud probability across independent evidence families, balanced against clearing signals."*
  > *"When the case is borderline, the agent doesn't blindly ask questions. It scores every possible evidence request by expected decision impact — would either answer actually change the recommended action? Only the highest-value request is made. HHG-014 shows customer validation selected at information value 1.0, with the alternatives and their scores displayed."*
- **Highlight (Human-in-the-Loop)**:
  - Set `EVIDENCE_REQUEST_MODE=human_in_loop` in `.env` before the demo and the agent **pauses** at `MORE_EVIDENCE_REQUIRED`.
  - The Uncertainty tab shows the request with its info value and a response input with quick-fill presets. Submit a response live (or let a judge type one) and watch the reassessment update probability, risk level, and the NBA set in real time.
  - In default `simulated` mode, the same loop runs with a synthetic response always labelled `origin=simulated` — audit-safe and honest.

---

### Phase 4: Governed Next Best Action & Graph Canvas (3:15 – 4:30)
- **Visual**: Switch to the **Governed NBA** tab and **Interactive Graph Canvas**.
- **Narrative**:
  > *"AI recommendations must never bypass institutional policy. Our Policy Engine independently gates actions into permission tiers: Auto-Execute, L1 Team Lead approval, and L2 Fraud Manager approval. Every recommendation documents the policy rule cited, a why-now rationale grounded in the current state, and the alternatives that were rejected."*
- **Highlight (Approval Execution)**:
  - Approve or reject a pending L1/L2 action as the analyst. The decision is re-validated against policy, **the action actually executes under the approver's authority** (or is refused), and `approval_granted` / `action_executed` audit events appear in the timeline.
- **Highlight**:
  - **Interactive Graph Canvas**: Click on the **Customer**, **Card**, or **Device** node to open the **Graph Inspector Drawer** showing entity attributes and linked evidence IDs.
  - **Zoom & Pan**: Use scroll wheel to zoom into device clusters; click **Reset Zoom** to re-center.

---

### Phase 5: Auditability, Memory & Live Benchmark (4:30 – 5:00)
- **Visual**: Point to the **Graph Case ID** badge (`CASE-2016-HHG-014`) and open the **Benchmark / Validation** tab.
- **Narrative**:
  > *"Every completed investigation is persisted as an InvestigationCase vertex — linked to customer, card, transactions, and device profile. Future investigations retrieve this memory through the same graph traversal they use for everything else, and prior agent cases feed a dedicated risk channel. The memory loop genuinely closes."*
  > *"The Benchmark tab shows live per-case results loaded from the actual artifacts — 20/20 cases, 600/600 checkpoints, verified by a 257-test suite."*
- **Wrap-up**: show the **plan trace** evidence: each case records which tools the planner chose and why — different cases demonstrably run different investigation paths.

---

## What NOT to Do During Demo
- **Do NOT** change `.env` or toggle `STRICT_GRAPH_BACKEND` while the server is running.
- **Do NOT** spam the investigation button repeatedly while an execution is in flight.
- **Do NOT** resize the window to mobile width while demonstrating the D3 graph network.

---

## Emergency Recovery Procedure
- **If the screen displays `TigerGraph Unreachable (503)`**:
  1. Open [savanna.tgcloud.io](https://savanna.tgcloud.io).
  2. If the cluster status is **Suspended**, click **Resume/Start**.
  3. Wait 3 minutes until status is **RUNNING**.
  4. Refresh the Command Center page (`F5`).
