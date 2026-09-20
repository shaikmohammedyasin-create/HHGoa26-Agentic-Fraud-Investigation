# HHGOA'26 — Phase D.6 Prototype Polish: Gap Analysis

## 1. What Is Already Good
- **Rock-solid Backend & Engine**: 221/221 tests passing, 600/600 IEEE checkpoints verified against live TigerGraph Savanna Cloud in strict fail-closed mode (`STRICT_GRAPH_BACKEND=1`).
- **Complete End-to-End Investigation Pipeline**: Ingests 20 benchmark case triggers, executes 12-stage investigation, gathers multi-source evidence (live GSQL, closed cases, customer interaction), computes noisy-OR risk assessment, and evaluates policy governance.
- **FastAPI Surface**: Clean endpoints for `/api/cases`, `/api/investigations/{id}/full`, `/api/investigations/{id}/graph`, and `/api/investigations/{id}/approvals/{id}/decide`.
- **Vanilla Modern Tech Stack**: Fast, responsive HTML5/CSS3/ES6 implementation without bloated front-end frameworks or build step dependencies.

---

## 2. What Is Confusing to a Judge
- **Fragmented Investigation Narrative**: The left panel stepper is a static checklist of 8 generic steps. It does not visually convey the actual investigative causal chain:
  `TRIGGER → EVIDENCE → PATTERN → RISK → UNCERTAINTY → ADDITIONAL EVIDENCE → REASSESSMENT → NBA → POLICY → APPROVAL → CASE OUTCOME`.
  A judge watching a demo cannot immediately answer: *"Why did the agent make this decision?"*
- **Buried Uncertainty Cycle**: Uncertainty items are placed in Tab 2, while Evidence Requests are in Tab 3, and NBA changes are in Tab 4. The single most impressive agentic capability—*asking targeted questions, resolving ambiguity, and shifting risk and policy*—is scattered across separate panes.
- **Blended Governance Hierarchy**: Actions appear as flat rows with "L1" or "Auto". The strict 4-tier separation:
  `Agent Recommendation → Policy Engine Rules → Permission Matrix → Human Approval Action`
  is obscured.

---

## 3. What Is Visually Weak
- **Opaque Risk Assessment**: The threat banner displays a single number (`0.429`) and a progress bar. The rich noisy-OR `score_breakdown` table (channel weights for trigger, testing sequence, proxy, device, customer denial) is completely invisible.
- **Non-Interactive Graph Canvas**: Nodes render as static colored circles. Clicking or hovering over an entity does not show why that node matters to the case, its attributes, or which evidence items reference it.
- **Evidence Cards Lack Visual Hierarchy**: High-severity fraud indicators look visually identical to routine background history checks.
- **Single-Label Pattern Presentation**: Only the primary pattern string is shown; secondary patterns and candidate confidence rankings are hidden.

---

## 4. What Important Evidence Is Currently Hidden
1. **`score_breakdown` (Noisy-OR Contributions)**: Stored in DB and computed per DECISIONS.md D7, but zero UI elements display it.
2. **`evidence.provenance` & `claim_type`**: Each evidence item has `evidence_id`, `step`, `claim_type` (`observed_fact`, `derived_inference`, `model_score`), and `query` ref, but only raw ref strings were displayed.
3. **`nba.alternatives_rejected` & `expected_impact`**: Hardened in Phase D.5 to provide counterfactual explanations (e.g. why `BLOCK_CARD` was rejected in favor of `MONITOR_CARD`), but omitted from the front-end view.
4. **`uncertainty.resolved_by` & `resolution_impact`**: Shows the probability shift (e.g. `0.43 → 0.76`) caused by customer verification, but was never rendered.
5. **`pattern_candidates`**: Multi-candidate pattern scores and supporting signals are stored in backend payloads but never exposed.

---

## 5. What Can Fail During a Live Demo
- **Browser `alert()` Popups**: API errors and approval confirmations currently trigger native browser dialogs, which look unpolished and block the browser UI.
- **Empty States**: If an analyst selects a case before running it, standard empty placeholders don't guide them on what the trigger represents.
- **Unclear Status in Case of TigerGraph Disconnect**: If Savanna sleeps or network drops, status dots turn red without providing actionable diagnostic info to the judge/presenter.
- **Accidental Double-Submissions**: No visual lock/dimmer on the canvas and panels during live investigation.

---

## 6. High-Selection-Value Changes to Implement
| Priority | Feature Area | High-Value Implementation |
| :--- | :--- | :--- |
| **P0** | **Investigation Story Ribbon** | Interactive 11-stage causal narrative stepper mapping the exact progression from Trigger to Case Outcome. |
| **P0** | **Evidence-First Explainability** | Expose `claim_type` badges, `evidence_id` chips, noisy-OR `score_breakdown` decomposition card, and entity tags. |
| **P0** | **Uncertainty & Reassessment Loop** | Unified before/after reassessment card showing open ambiguity ➔ request sent ➔ response received ➔ probability delta & action shift. |
| **P1** | **Governed Policy & NBA Console** | Clear 4-tier decision funnel with `evidence_ids` links, `alternatives_rejected` counterfactual justifications, and `expected_impact`. |
| **P1** | **Graph Node Inspector** | Clicking any graph node opens an inspector drawer explaining its investigative relevance, attributes, and linking to related evidence. |
| **P1** | **Demo-Safe Failure UX & Toasts** | Non-blocking toast notification system, diagnostic health modal, and graceful error banners. |
| **P2** | **Visual Polish & Micro-interactions** | Enhanced typography, refined contrast, status badges, and smooth state transitions. |
