# Frontend Design Direction & Evidence Contract

> Project: **FraudLens &times; Agentic Fraud Investigation Platform**  
> Visual Direction: **FraudLens Command Center (TigerGraph Native)**  
> Reference: [FraudLens TigerGraph](https://github.com/samarthputhraya/fraudlens-tigergraph)

---

## 1. Product Contract & Purpose

| Dimension | Specification |
| :--- | :--- |
| **Product Purpose** | Autonomous, evidence-grounded, policy-controlled fraud investigation console. Transforms raw transactional fraud alerts into explainable multi-hop graph dossiers, calibrated Bayesian risk odds, and governed Next Best Actions (NBAs). |
| **Primary Audience** | Tier 1 Fraud Analysts, Tier 2 Compliance Officers, and Financial Crime Investigators conducting high-volume alert triage and case audits under strict SLA windows. |
| **First-Scan Priority** | 1. **Dossier Case Identity & Flagged Amount**<br>2. **Threat Assessment Verdict & Fraud Probability Score**<br>3. **Knowledge Graph Subgraph & Shared Device Neighbors**<br>4. **Action Routing Governance (Auto vs. L1 vs. L2 Approval)** |
| **Design Tone** | **Dense, Calm, Technical, Refined, Utilitarian.** Absolutely zero consumer landing page hero fluff, zero saturated neon gradients, and zero decorative animations that impede fast operational scanning. |
| **Memorable Detail** | **TigerGraph Orange Accent (`#F58025`)** used with surgical restraint against deep matte Ink slate (`#06080B` to `#0E1218`), accompanied by live GSQL traversal latency tracking and interactive evidence re-proving. |
| **Target Viewports** | `1920x1080` (Standard Analyst Multi-Monitor), `1440x900` (Workstation Laptop), `1200x800` (Tablet / Responsive breakpoint). |

---

## 2. 6-State Content Contract

| State | Trigger & Condition | Visible User Feedback | Safe Next Action |
| :--- | :--- | :--- | :--- |
| **1. Empty State** | Case selected that has not yet been executed through the investigation pipeline. | Clean matte card explaining: *"Case not yet investigated. Click 'Run Investigation' to execute live TigerGraph queries and agent assessment."* | User clicks primary orange CTA button `Run Investigation` (`#btnInvestigate`). |
| **2. Loading State** | Investigation running (`#btnInvestigate` clicked). | 1. Button disables and states `Investigating...`<br>2. Stepper highlights Step 3 (Live Graph Traversal)<br>3. Live substep pill displays `1/4`–`4/4`<br>4. Canvas displays pulsating concentric orange radar scans with live elapsed query timer (`0.0s`). | User observes live query latency; non-blocking canvas ensures UI responsiveness. |
| **3. Partial / Ambiguous State** | Investigation completed with open decision ambiguity (`verdict: uncertain`). | 1. Verdict badge reflects `UNCERTAIN` in amber tint (`#EDB341`)<br>2. Active Decision Ambiguity card outlines expected information gain<br>3. Agent enters paused state awaiting verification. | Analyst inputs customer validation response or clicks quick simulation buttons (`Customer Confirmed`, `Customer Denied`, `No Reply`). |
| **4. Error State** | API failure, network timeout, or invalid case dossier payload. | 1. Non-blocking red toast notification slides in bottom-right with exact server error description<br>2. Buttons re-enable safely<br>3. Status dots flag degraded connectivity. | User can dismiss toast, re-click investigation, or inspect `#healthModal` diagnostics. |
| **5. Success State** | Pipeline execution finishes cleanly with verified verdict (`FRAUD` or `LEGITIMATE`). | 1. Verdict badge lights up in high-contrast crimson (`#EF5A50`) or emerald (`#3CC585`)<br>2. Probability bar fills smoothly to calibrated percentage<br>3. Knowledge graph populates 2-hop topology<br>4. Success toast confirms completion. | Analyst reviews NBA recommendations, inspects evidence provenance with "Re-prove", or approves policy actions. |
| **6. Permission State** | High-impact action (e.g. `BLOCK_CARD`, `FILE_SAR`) requires Level 1 Analyst or Level 2 Compliance authorization. | Action card displays dedicated amber/red routing pill (`L1 Analyst` or `L2 Compliance`) with audit rule citation and `Approve` / `Reject` buttons. | Authorized analyst clicks `Approve` or `Reject`, updating the immutable SQLite audit ledger with their identifier. |

---

## 3. Rendered Finish Gate Audit

### Visual Hierarchy & Spacing Rhythm
- **Left Navigation Rail (`76px`)**: Compact rail with brand insignia, navigation buttons for Queue, Live, Case File, Approvals, and Insights.
- **Top Command Bar (`58px`)**: Fixed height with backdrop blur. Brand title, subtitle, case dropdown selector, and status indicators.
- **5 Dedicated Primary Views**:
  - **Queue View**: High-level exposure KPIs, segmented filter group, search input, and high-density alert table.
  - **Live View**: Live threat header, 11-stage pipeline progression stepper, and full knowledge graph stage with live query latency tracking.
  - **Case File View**: Central investigation workspace with dossier hero, 6-metric tile strip, and analytical subtabs (Summary, Evidence Dossier, Knowledge Graph, Risk Analysis, Uncertainty & HITL, Governed NBAs, FinCEN SAR Document, and Audit Timeline).
  - **Approvals View**: Cross-case governance inbox with L1/L2 routing and inline decision submission.
  - **Insights View**: 20-case IEEE-CIS validation dashboard with structural checkpoint evaluation and case runs table.

### Typography & Anti-Slop Discipline
- Preconnected Google Fonts: **`Inter`** for clean geometric UI hierarchy + **`JetBrains Mono`** for technical identifiers, hashes, and tabular numbers.
- 100% elimination of AI slop:
  - 0% generic tech gradients (pure matte Ink slate surfaces `#06080B`, `#0E1218`).
  - 0% neon/cyberpunk styling (monochrome slate base with `#F58025` TigerGraph orange accent).
  - 0% nested cards (flat panel architecture with clean hairline dividers).
  - 0% oversized vanity stat monuments (proportional monospace figures).
  - 0% marketing fluff (immediate operational command interface).

---

## 4. Verification & Status

* **HTML Structure**: All required DOM IDs verified present.
* **JavaScript Syntax**: `node -c` verified for all frontend modules (`api.js`, `graph.js`, `app.js`).
* **API Integration Tests**: `pytest` passed 250 tests cleanly with 0 regressions.
* **Runtime Status**: Ready for deployment with full FastAPI static mounting.
