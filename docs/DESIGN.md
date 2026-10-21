# Design System: FraudLens &times; Agentic Fraud Investigation Platform

> Formal product design specification, token taxonomy, and investigative workflow architecture for FraudLens, adapted from the reference architecture ([FraudLens TigerGraph](https://github.com/samarthputhraya/fraudlens-tigergraph)).

---

## 1. Surface Archetype & Philosophy

According to the **Surface-First Discipline** (ECC Engineering Standards &sect;9):
* **Primary Archetypes**:
  * `Operate` &mdash; Alert queue triage, approval inboxes, policy routing, human-in-the-loop decisions.
  * `Command/Inspect` &mdash; In-depth case file dossiers, multi-hop knowledge graph inspection, calibrated Bayesian risk odds breakdown, FinCEN SAR documents.
  * `Explore` &mdash; Knowledge graph topology explorer, device neighborhood clustering, historical case precedents.
* **Anti-Goals**:
  * No marketing hero banners or consumer landing page fluff in operational surfaces.
  * No generic SaaS gradient bloat or neon cyberpunk styling.
  * No nested cards-in-cards or oversized vanity metric monuments.
  * No fake data or fabricated citations &mdash; every metric must come from real graph queries or model scores.

The design philosophy prioritizes **density over decoration**, **traceable evidence over assertions**, and **instant scannability for financial crime investigators**.

---

## 2. Color System & Semantic Tokens

### Core Palette (Ink Slate & TigerGraph Orange)

| Token | Hex Equivalent | Role & Application |
| :--- | :--- | :--- |
| `--ink-950` | `#06080B` | Deepest root ground, left navigation rail background |
| `--ink-900` | `#0A0D12` | Command bar ground & viewport background |
| `--ink-850` | `#0E1218` | Primary panel container surface, table wrapper, dossier cards |
| `--ink-800` | `#12171F` | Table row hover, active nav button, input backdrops |
| `--ink-750` | `#171D27` | Subtle inner dividers & table borders |
| `--ink-700` | `#1F2733` | Standard hairline borders & control rules |
| `--ink-600` | `#2B3544` | Inactive chip borders & secondary elements |
| `--ink-400` | `#6A7688` | Table headers, secondary labels, metadata keys |
| `--ink-200` | `#C3CBD7` | Primary body text & readable content |
| `--ink-100` | `#E7EBF1` | Headings, case identifiers, tabular numerals |
| `--tg-500` | `#F58025` | TigerGraph signature orange accent; active states, primary CTA |
| `--tg-400` | `#F89A50` | Vibrant orange hover states & prominent indicators |
| `--tg-300` | `#FBB27A` | Soft orange text, rule highlights, and badges |

### Semantic State Palette

| Semantic State | Base Color | Tint Soft | Border Tint | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **Fraud / Critical** | `#EF5A50` | `#3A1716` | `#7A2A25` | Confirmed fraud, high probability, rejected actions |
| **Legitimate / Clear** | `#3CC585` | `#0F2A1E` | `#1E6644` | Cleared transactions, verified cardholder, approved actions |
| **Uncertain / Ambiguous** | `#EDB341` | `#33260C` | `#7A5A18` | Decision ambiguity, L1 review needed, evidence gaps |

### Agent Role Signatures

| Agent Role | Color | Scope & Responsibilities |
| :--- | :--- | :--- |
| **Lead Investigator** | `#F58025` (Orange) | Hypothesis formation, orchestrator coordination, stopping rule |
| **Transaction Agent** | `#5EA8FF` (Sky Blue) | Card baseline, 48h bursts, transaction velocity |
| **Identity & Device** | `#A48BFA` (Lavender) | Client hardware fingerprinting, IP/Device co-usage |
| **Network & Ring** | `#2FD3BE` (Teal) | Multi-card syndicate detection, rare shared devices |
| **Precedent / Memory** | `#F277B5` (Pink) | Closed historical case retrieval, GraphRAG matching |
| **Compliance Reviewer** | `#C3CCD8` (Silver) | Policy rule verification, FinCEN SAR narrative |

---

## 3. Information Architecture & Navigation

The platform provides 5 dedicated top-level views via a compact `76px` Nav Rail:

```
┌──────┬─────────────────────────────────────────────────────────────────┐
│ Rail │ Top Header: FraudLens Command Center · Case Selector · Status   │
│ (76) ├─────────────────────────────────────────────────────────────────┤
│      │ Active Viewport:                                                │
│ [Q]  │ 1. Alert Queue: Triage table, filters, confirmed exposure total │
│ [L]  │ 2. Live: 11-stage pipeline, GSQL timer, live threat gauge, graph│
│ [C]  │ 3. Case File: Central investigation workspace & deep dossier    │
│ [A]  │ 4. Approvals: Governed L1/L2 inbox across all institutional cases│
│ [I]  │ 5. Insights: 20-case IEEE-CIS validation & checkpoint benchmark │
└──────┴─────────────────────────────────────────────────────────────────┘
```

---

## 4. Case Investigation Workspace Architecture (Case File View)

The Case File workspace is organized into focused analytical subtabs:

1. **Summary & Typology**: Executive case narrative, pattern description, candidate breakdown, and stop reason.
2. **Evidence Dossier**:
   * Claims with `SourceChip` (`Graph`, `Policy doc`, `Customer`, `External`).
   * Parsed GSQL query references: `query:get_card_transaction_history(...)`.
   * **Re-prove Feature**: Interactive popover modal allowing analysts to re-run graph queries and inspect live execution latency (ms), row count, and returned data sample.
   * Clickable `IdChip`s that focus entities in the graph and filter evidence.
3. **Knowledge Graph Explorer**:
   * HTML5 Canvas with custom topological layout, node shapes (Customer ellipse, Card rounded-rect, Flagged star/pulse, Device hexagon, ClosedCase diamond), and link relationship labels.
   * Slide-up Entity Inspector drawer showing node role, relevance, properties, and "Filter related evidence" CTA.
4. **Explainable Risk (Noisy-OR)**:
   * Baseline model score starting point.
   * Independent risk channels table with conditional weights and observed findings.
   * Pre-evidence vs. post-evidence probability comparisons.
5. **Uncertainty & Evidence Gaps**:
   * Expected information gain calculation.
   * Active ambiguity cards with quick simulation buttons (`Customer Confirmed`, `Customer Denied`, `No Reply`) and custom text input.
   * Submission triggers live backend re-evaluation via `POST /investigations/{id}/evidence`.
6. **Governed Next Best Actions (Policy Matrix)**:
   * Action diff: Initial recommendation vs. Final recommendation (`kept`, `added`, `removed`).
   * Policy rules cited (R1–R11) with regulatory routing (`Auto`, `L1 Analyst`, `L2 Compliance`).
   * Inline `Approve` and `Reject` buttons calling backend approval endpoints.
7. **FinCEN SAR Document**:
   * Complete formal filing draft ready for regulatory submission.
   * Part I: Subjects table, Part II: Narrative, Part III: Basis for filing, L2 Compliance signature block.
8. **Audit Timeline**:
   * Chronological event log with state transitions, actor attribution, and timestamps.

---

## 5. Verification & Acceptance Criteria

* **Automated Test Coverage**: 250 passing pytest tests with zero failures.
* **JavaScript Syntax**: Clean `node -c` validation across `api.js`, `graph.js`, and `app.js`.
* **API Endpoints**: 100% compliant with FastAPI models, including `/api/cases`, `/api/investigations/{id}/full`, `/api/investigations/{id}/graph`, `/api/approvals`, and `/api/reprove`.
* **Accessibility**: Full semantic landmarks (`role="banner"`, `role="main"`, `role="tablist"`, `role="tab"`, `role="tabpanel"`).
