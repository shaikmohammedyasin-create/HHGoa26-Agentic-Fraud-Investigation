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

### Phase 3: Noisy-OR Decomposition & The Uncertainty Loop (2:00 – 3:15)
- **Visual**: Scroll to the **Risk Analysis** and **Uncertainty Loop** cards.
- **Narrative**:
  > *"Rather than outputting a black-box score, our engine decomposes fraud probability mathematically using Noisy-OR channel aggregation across Velocity, Network Linkage, Device Profile, and Geolocation, balanced against clearing signals."*
  > *"Because HHG-014 falls in the borderline uncertainty zone (probability 0.528), the agent does NOT guess. It identifies the missing evidence, issues a structured customer verification request, and reassesses the case upon response."*
- **Highlight**:
  - Show **Initial vs. Final Assessment**: Probability and recommended actions dynamically update after the simulated customer-validation evidence request reaches its response state.

---

### Phase 4: Governed Next Best Action & Graph Canvas (3:15 – 4:30)
- **Visual**: Switch to the **Governed NBA** tab and **Interactive Graph Canvas**.
- **Narrative**:
  > *"AI recommendations must never bypass institutional policy. Our Policy Engine independently gates actions into permission tiers: Auto-Execute, L1 Team Lead approval, and L2 Fraud Manager approval. Every recommendation documents the policy rule cited and the alternatives that were rejected."*
- **Highlight**:
  - **Interactive D3 Graph**: Click on the **Customer** or **Card** node to open the **Graph Inspector Drawer** showing entity attributes and linked evidence IDs.
  - **Zoom & Pan**: Use scroll wheel to zoom into device clusters; click **Reset Zoom** to re-center.

---

### Phase 5: Auditability & Graph Persistence (4:30 – 5:00)
- **Visual**: Point to the **Graph Case ID** badge (`CASE-2016-HHG-014`).
- **Narrative**:
  > *"Every completed investigation is persisted as an InvestigationCase vertex back into the TigerGraph schema. This serves as organizational memory: future investigations automatically retrieve this case during GraphRAG retrieval."*
- **Wrap-up**:
  > *"In the official 20-case benchmark, this system passed 600/600 IEEE checkpoints, achieved 95% verdict accuracy, 90% primary pattern accuracy, and persisted 20/20 cases to live TigerGraph, backed by a 228-test passing suite."*

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
