# HHGOA'26 — Targeted Pattern Reasoning Hardening Report

**Project:** TigerGraph Agentic Fraud Investigation — HHGOA'26  
**Backend Mode:** Live TigerGraph Savanna Cloud (`fraud_investigation`) in Strict Mode (`STRICT_GRAPH_BACKEND=1`)  
**Date:** 2026-09-20  
**Status:** **PATTERN HARDENING SUCCESSFUL**

---

## 1. Executive Summary & Comparative Metrics

The objective of this targeted hardening phase was to resolve primary fraud-pattern classification mismatches without hardcoding case IDs, without benchmark-specific branches, without altering verdict thresholds, SAR rules, NBA policy, or case pack data, and strictly adhering to the official challenge pattern definitions.

| Metric | Baseline (Frozen D.6) | Hardened Result | Delta / Status |
|---|---|---|---|
| **Primary Pattern Accuracy** | **11/20 (55.0%)** | **18/20 (90.0%)** | **+35.0% (+7 cases matched)** |
| **Pattern Candidate Recall** | **18/20 (90.0%)** | **18/20 (90.0%)** | **Preserved (0 regressions)** |
| **Verdict Accuracy** | **18/20 (90.0%)** | **19/20 (95.0%)** | **+5.0% (+1 case matched: HHG-004)** |
| **SAR Accuracy** | **18/20 (90.0%)** | **18/20 (90.0%)** | **Preserved (0 regressions)** |
| **Next-Best Action Accuracy** | **15/20 (75.0%)** | **15/20 (75.0%)** | **Preserved (0 regressions)** |
| **Graph Persistence Rate** | **20/20 (100.0%)** | **20/20 (100.0%)** | **Preserved (0 regressions)** |
| **IEEE Checkpoint Compliance** | **600/600 (100.0%)** | **600/600 (100.0%)** | **Preserved (0 regressions)** |
| **Unit & Integration Tests** | **221 passed** | **228 passed** | **+7 new tests, 0 failures** |

---

## 2. Root Cause Audit & Generalized Solutions

### A. Live TigerGraph Identity Signal Loss & None-String Conversion
- **Audit Findings:** In `backend/graph/tg_adapter.py`, `_to_identity()` suffered from two issues:
  1. It converted missing vertex attributes via `str(attrs.get("..."))`, turning `None` into the string `"None"`. Consequently, checks like `if rec.device_status == "New"` or `if rec.proxy` failed because attributes were either `"None"` strings or completely unpopulated.
  2. The query mapping omitted `proxy` and `match_status`, preventing downstream identity anomalies from being recognized.
- **Generalized Fix:**
  - Standardized `_to_identity()` to clean attribute values and only store non-null, non-empty strings.
  - Correctly mapped `proxy` (from `id_23` / proxy fields) and `match_status` (from `id_34` / match fields).
  - Added a fallback in `get_transaction_identity()` to enrich missing vertex attributes from the canonical transaction dataset if TigerGraph vertex attributes were sparse.

### B. Live TigerGraph `card_amount_stats` Dict Parsing
- **Audit Findings:** The GSQL query `card_amount_stats` returns a top-level dictionary `{"avg_amt": ..., "n": ...}`, whereas `tg_adapter.py` parsed `res.get("result", [])`. This caused the parser to find an empty list and default `avg_card_amount` to `0.0`. Without historical card average amounts, `unusual_amount` could not be reliably established for card-not-present fraud detection.
- **Generalized Fix:** Updated `get_card_amount_stats()` in `tg_adapter.py` to handle both top-level dictionary outputs and nested list outputs. In `backend/agents/orchestrator.py`, added a fallback to compute average transaction amount from retrieved `card_history` if the stats query returns 0.

### C. Pattern Detector ATO vs. CNP New Device Tiebreaker
- **Audit Findings:**
  1. In `backend/risk/pattern_detector.py`, `account_takeover` received a `+0.15` bonus simply if `new_device and mixed_channel`, which conflated any online transaction accompanied by prior in-person history with account takeover.
  2. The tiebreaker between ATO and CNP-New-Device only demoted ATO if `mixed_channel=False`. However, legitimate cardholders frequently make both in-person and online purchases. Per official definitions, ATO requires mixed-channel activity *inconsistent with the cardholder* or credential-theft anomalies, whereas `new_device` is the hallmark of `card_not_present_new_device`.
- **Generalized Fix:**
  - Confined the ATO boost strictly to genuine identity/credential mismatches (`match_flag_anomaly=True`).
  - Revised Tiebreaker 1: When `new_device=True` on an online transaction, `card_not_present_new_device` takes precedence over ATO unless there is explicit credential-theft evidence (`match_flag_anomaly=True`).
  - Revised Tiebreaker 2: When `new_device=True` and `burst_online >= 2` with strong CNP velocity, the README pattern definition for CNP fraud is respected while retaining both as top candidates.

---

## 3. Case-by-Case Benchmark Analysis (20 Cases)

| Case | Flagged Txn | Expected Pattern | Baseline Pattern | Actual Pattern | Match Status | Primary Selection Rationale & Candidates |
|---|---|---|---|---|---|---|
| **HHG-001** | 3514030 | `none` | `none` | `none` | **MATCH** | Normal transaction activity; no pattern scores above 0.25 threshold. |
| **HHG-002** | 3478782 | `none` | `none` | `none` | **MATCH** | Low risk, ordinary retail spending; insufficient pattern evidence. |
| **HHG-003** | 3530164 | `none` | `none` | `none` | **MATCH** | Routine domestic transaction; no anomaly pattern detected. |
| **HHG-004** | 3583227 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | Burst of 8 online transactions in 48h; amount well above historical average. Verdict improved from uncertain to fraud (0.915 probability). |
| **HHG-005** | 3523199 | `card_not_present_new_device` | `undocumented` | `card_not_present_new_device` | **IMPROVED** | Identity record recovered `device_status="New"`. Differentiated from ATO due to absence of match flag anomaly. |
| **HHG-006** | 3476682 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | Burst of 4 online transactions within 48h with elevated transaction amount. |
| **HHG-007** | 3514948 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | Online transaction burst within 48h window. |
| **HHG-008** | 3558054 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | Rapid burst of 17 online transactions within 48h. |
| **HHG-009** | 3581141 | `card_not_present_fraud` | `undocumented` | `undocumented` | **DIVERGENT (EXPLAINED)** | Flagged transaction is $30.02 (below card average of $61.17); no 48h burst exists. Coordinated device sharing across 20 other cards is present. Fully consistent with Policy R9 (reporting undocumented coordinated abuse rather than forcing into single CNP). |
| **HHG-010** | 3506725 | `card_not_present_new_device` | `undocumented` | `card_not_present_new_device` | **IMPROVED** | Identity record correctly extracted `device_status="New"`; classified cleanly under CNP-New-Device. |
| **HHG-011** | 3583368 | `card_not_present_fraud` | `card_testing` | `card_testing` | **DIVERGENT (EXPLAINED)** | Graph query detected 3 small online authorizations ($6.33, $6.39, $6.35) followed by a larger $131.30 purchase. Strictly adheres to official challenge definition of `card_testing`. Secondary candidate is `card_not_present_fraud` (score 0.50). |
| **HHG-012** | 3553342 | `none` | `none` | `none` | **MATCH** | Clean transaction history; low risk score; no pattern candidates qualify. |
| **HHG-013** | 3526826 | `card_not_present_new_device` | `account_takeover` | `card_not_present_new_device` | **IMPROVED** | Device marked "New" for account; ordinary mixed-channel demoted from ATO because match flags showed no credential tampering. |
| **HHG-014** | 3478561 | `card_not_present_new_device` | `account_takeover` | `card_not_present_new_device` | **IMPROVED** | Device marked "New" with proxy/anonymous connection; correctly outranked ATO in absence of match flag anomaly. |
| **HHG-015** | 3464869 | `card_not_present_new_device` | `account_takeover` | `card_not_present_new_device` | **IMPROVED** | Device marked "New"; ordinary channel coexistence does not imply credential takeover without match anomalies. |
| **HHG-016** | 3534820 | `card_not_present_new_device` | `undocumented` | `card_not_present_new_device` | **IMPROVED** | Identity record parsed `device_status="New"`; candidate scored 0.70 and ranked as primary. |
| **HHG-017** | 3450629 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | 8 online transactions in 48h; device shared across multiple accounts; high fraud probability. |
| **HHG-018** | 3491361 | `card_not_present_fraud` | `card_not_present_fraud` | `card_not_present_fraud` | **MATCH** | 12 online transactions within 48h window. |
| **HHG-019** | 3503878 | `account_takeover` | `account_takeover` | `account_takeover` | **MATCH** | Mixed-channel activity combined with explicit `match_status=0` (M4 match flag anomaly); genuine credential theft. |
| **HHG-020** | 3509359 | `card_not_present_new_device` | `account_takeover` | `card_not_present_new_device` | **IMPROVED** | Device marked "New"; ATO correctly demoted in favor of CNP-New-Device. |

---

## 4. Deep-Dive on Discrepant Cases (HHG-009 and HHG-011)

### HHG-009: Grounded Justification for `undocumented`
- **Expected:** `card_not_present_fraud`
- **Actual:** `undocumented`
- **Official Definition of `card_not_present_fraud`:**
  > *"Online card use without the card. Amounts/products inconsistent with card history. Often a burst of 2–4 online transactions within 48h. A single unusual online purchase is ambiguous."*
- **Evidence Findings:**
  - Flagged transaction is $30.02. Historical card average is $61.17 (not unusual/inconsistent).
  - Burst in 48h: 0 (isolated single transaction).
  - Device info is `unknown | unknown | unknown | unknown`, but graph analysis reveals this identical profile is shared across 20 other cards.
  - Per IEEE Competition Policy R9 and Section 5 of the challenge instructions, an isolated low-dollar dispute linked to multi-card device syndicates without card-history inconsistency represents coordinated cross-account abuse, accurately classified as `undocumented`.

### HHG-011: Grounded Justification for `card_testing`
- **Expected:** `card_not_present_fraud`
- **Actual:** `card_testing` (with `card_not_present_fraud` as secondary candidate)
- **Official Definition of `card_testing`:**
  > *"Three or more tiny online authorizations, often under $5, followed by a larger purchase. Confirmed by the sequence itself."*
- **Evidence Findings:**
  - Graph query `tiny_transaction_sequence` identified 3 authorizations ($6.33, $6.39, $6.35) in a 2-hour window directly preceding the flagged purchase of $131.30.
  - The sequence structure strictly fulfills the official card testing typology definition.
  - Per Step 7 guidelines, `card_testing` is properly retained as primary because the evidence objectively supports the sequence definition, while `card_not_present_fraud` is captured as an active secondary candidate (score 0.50).

---

## 5. Regression Gate & Test Verification

All regression gate conditions are met:
1. **No Case ID Hardcoding:** Verified across all files (`pattern_detector.py`, `tg_adapter.py`, `orchestrator.py`).
2. **No Policy/Threshold Changes:** Fraud thresholds, SAR rules (§4), and NBA policy engine remain untouched.
3. **No Metric Regressions:**
   - Checkpoints: **600/600 (100.0%)**
   - Verdict: **19/20 (95.0%)** (improved from 18/20)
   - SAR: **18/20 (90.0%)** (maintained)
   - NBA: **15/20 (75.0%)** (maintained)
   - Graph Persistence: **20/20 (100.0%)** (maintained)
4. **Unit Test Suite:**
   - `pytest -q`: **228 passed in 51.62s** (zero failures, zero warnings).

---

## 6. Final Decision

**PATTERN HARDENING SUCCESSFUL**
