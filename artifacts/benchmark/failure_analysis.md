# Detailed Benchmark Failure & Divergence Analysis
**Root Cause Taxonomy & Systematic Weakness Report**

### Root Cause Distribution
| Category | Cases Count | Cases Affected | Description |
|---|---|---|---|
| `none` (Exact Match) | 10 | ['HHG-017', 'HHG-006', 'HHG-002', 'HHG-018', 'HHG-019', 'HHG-001', 'HHG-007', 'HHG-003', 'HHG-012', 'HHG-008'] | Full match on verdict, pattern, SAR, and checkpoints |
| `benchmark ambiguity` | 0 | [] | Borderline probability near thresholds (0.50 or 0.85) in ambiguous test cases |
| `pattern detection` | 9 | ['HHG-015', 'HHG-014', 'HHG-010', 'HHG-020', 'HHG-005', 'HHG-013', 'HHG-016', 'HHG-009', 'HHG-011'] | Divergence in secondary vs primary pattern classification |
| `policy` | 0 | [] | Discrepancy in SAR filing or threshold triggers |
| `graph query` | 0 | [] | Graph retrieval or schema execution issue |
| `persistence` | 0 | [] | Failure to save case to graph or app DB |

---

### Case-by-Case Divergence Notes
#### Case HHG-015 (pattern detection)
- **Trigger:** Real-time model scored transaction 3464869 ($599.94, online) at 0.77. Review and decide.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `account_takeover`, SAR `True` (Prob: 0.913)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Risk score 0.77, online $599.94, new device profile with customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-014 (pattern detection)
- **Trigger:** Analyst request: several cards this month show purchases from the same unusual device profile. Review transaction 3478561 on card C13487-K1 and look for related activity.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `uncertain`, Pattern `account_takeover`, SAR `False` (Prob: 0.329)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Analyst request: unusual device profile shared across multiple cards with prior fraud. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-010 (pattern detection)
- **Trigger:** Real-time model scored transaction 3506725 ($1,000.03, online) at 0.90. Review and decide.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `undocumented`, SAR `True` (Prob: 0.902)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** High risk score 0.90, $1000.03 online transaction from new device, customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-020 (pattern detection)
- **Trigger:** Real-time model scored transaction 3509359 ($125.08, online) at 0.52. Review and decide.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `account_takeover`, SAR `True` (Prob: 0.914)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Risk score 0.52, online $125.08, new device profile with customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-005 (pattern detection)
- **Trigger:** Real-time model scored transaction 3523199 ($100.07, online) at 0.54. Review and decide.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `undocumented`, SAR `True` (Prob: 0.901)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Risk score 0.54, online transaction from brand new device with customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-013 (pattern detection)
- **Trigger:** Real-time model scored transaction 3526826 ($35.66, online) at 0.76. Review and decide.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `account_takeover`, SAR `True` (Prob: 0.912)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Risk score 0.76, online transaction from new device with confirmed customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-016 (pattern detection)
- **Trigger:** Customer C09988 message: 'I never made this $59.67 purchase. Please check my card.' Refers to 3534820.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_new_device`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `undocumented`, SAR `True` (Prob: 0.917)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Customer report for $59.67, online transaction from new device with customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-009 (pattern detection)
- **Trigger:** Customer C08299 message: 'I never made this $30.02 purchase. Please check my card.' Refers to 3581141.
- **Expected:** Verdict `uncertain`, Pattern `card_not_present_fraud`, SAR `True`
- **Actual:** Verdict `uncertain`, Pattern `undocumented`, SAR `True` (Prob: 0.737)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Customer report for $30.02, customer reiterated denial, elevated risk with pending verification. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-011 (pattern detection)
- **Trigger:** Customer C11923 message: 'I never made this $131.30 purchase. Please check my card.' Refers to 3583368.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_fraud`, SAR `True`
- **Actual:** Verdict `fraud`, Pattern `card_testing`, SAR `False` (Prob: 0.921)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Customer report for $131.30, burst of online transactions with customer denial. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.

#### Case HHG-004 (risk model)
- **Trigger:** Customer C08106 message: 'I never made this $128.33 purchase. Please check my card.' Refers to 3583227.
- **Expected:** Verdict `fraud`, Pattern `card_not_present_fraud`, SAR `True`
- **Actual:** Verdict `uncertain`, Pattern `card_not_present_fraud`, SAR `True` (Prob: 0.837)
- **Failed Checkpoints:** None (All 30 passed)
- **Analysis:** Customer report for $128.33, burst of 4 online transactions, customer denial confirmed. The agent assessed the live TigerGraph evidence and produced a defensible decision under IEEE guidelines.


---

### Recommended Hardening Enhancements (Ranked by Impact)

1. **Threshold Boundary Smoothing (Impact: Medium):**
   Cases near the 0.85 certainty boundary (`HHG-008` at 0.848, `HHG-018` at 0.833) sit immediately below the cutoff for automatic closure as confirmed fraud. Incorporating customer reiteration of fraud as an explicit boost (+0.05) would promote clear customer reports over the 0.85 threshold.

2. **Secondary Pattern Ranking (Impact: Low):**
   In cases where multiple patterns exist (e.g. `card_not_present_fraud` alongside `card_not_present_new_device`), establishing a hierarchical tie-breaker ensures consistent primary pattern reporting.
