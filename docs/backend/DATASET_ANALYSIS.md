# Dataset Analysis

## File Inventory

1. `transactions.csv`: Contains ~590,000 transaction records. Includes Vesta features, timestamps, channels, risk scores, and customer IDs.
2. `identity.csv`: Contains ~144,000 identity records associated with online transactions (joins on `TransactionID`). Includes device strings, OS, browser, etc.
3. `closed_cases_history.csv`: 5,565 historical investigations from July-Oct. Includes outcomes, patterns, connected cards, exposure, etc.
4. `case_pack.csv`: The 20 evaluation cases (Nov-Dec) with triggers.
5. `README.md` & `TigerGraph Agentic Fraud Investigation HHGOA.pdf`: The challenge requirements.

## Entity Relationships

Based on the suggested schema and data analysis:

*   **Customer** (`customer_id`): Owns multiple cards.
*   **Card** (`card1` to `card6` forming a card identity, or specifically `card_id` in cases): Makes transactions. Note: `customer_id` is derived from the issuer field.
*   **Transaction** (`TransactionID`): Belongs to a card/customer. Has an amount (`TransactionAmt`), timestamp (`ts`), and channel (`channel`).
*   **DeviceProfile** (from `identity.csv`): Associated with online transactions. Constructed from `DeviceInfo`, OS (`id_30`), browser (`id_31`), and screen (`id_33`).
*   **EmailDomain**: `P_emaildomain` (Purchaser) and `R_emaildomain` (Recipient) attached to transactions.
*   **BillingRegion**: Derived from `addr1` and `addr2`. Attached to transactions.
*   **ClosedCase** (`case_id`): Involves transactions, cards, and customers. Found in `closed_cases_history.csv`.

## Data Dictionary / Schemas

**transactions.csv**
*   `TransactionID`: PK.
*   `TransactionDT`, `TransactionAmt`: Time offset, amount.
*   `ProductCD`: Product code. 'W' is in-person (no identity record).
*   `card1` - `card6`: Card network, type, etc.
*   `addr1`, `addr2`: Billing region/country.
*   `P_emaildomain`, `R_emaildomain`: Emails.
*   `C1`-`C14`, `D1`-`D15`, `M1`-`M9`, `V1`-`V339`: Vesta engineered features.
*   `customer_id`: Assigned customer ID (e.g., C01234).
*   `ts`: Actual timestamp (YYYY-MM-DD HH:MM:SS)
*   `channel`: 'in_person' or 'online'.
*   `risk_score`: 0.0 to 1.0 (trigger).

**identity.csv**
*   `TransactionID`: FK to transactions.
*   `id_01` - `id_38`: Identity and connection details.
    *   `id_15`: Device New/Found.
    *   `id_23`: Proxy status.
    *   `id_30`: OS.
    *   `id_31`: Browser.
    *   `id_33`: Screen resolution.
*   `DeviceType`: mobile/desktop.
*   `DeviceInfo`: Hardware string.

**closed_cases_history.csv**
*   `case_id`: PK (e.g. CC-0001).
*   `customer_id`, `card_id`: Subject entities.
*   `opened_at`, `closed_at`: Timestamps.
*   `outcome`: 'confirmed_fraud' or 'cleared'.
*   `pattern`: The pattern type (or 'none').
*   `first_fraud_txn_id`: Where the fraud episode started.
*   `txn_ids`: Pipe-separated list of affected transactions.
*   `exposure_usd`: Financial impact.
*   `connected_card_ids`: Other cards implicated.
*   `actions_taken`: Pipe-separated list of actions.
*   `report_filed`: Yes/No.
*   `analyst_notes`: Narrative text describing the historical case.

**case_pack.csv**
*   `case_id`: PK (e.g. HHG-001)
*   `opened_at`: Timestamp.
*   `trigger_type`: 'risk_score', 'customer_report', 'analyst_request'.
*   `trigger_text`: The alert message.
*   `flagged_txn_id`: FK to the transaction that caused the alert.
*   `card_id`, `customer_id`: The subject of the alert.
*   `risk_score`: The score, if applicable.

## Fraud Patterns Supported
1.  **Card testing** (Policy R5)
2.  **Card-not-present fraud** (Policy R1-R4)
3.  **Card-not-present from new device**
4.  **Out-of-region use** (Policy R2, R3)
5.  **Account takeover**
*   **Undocumented**: (Must be identified dynamically).

## Ambiguities and Assumptions
*   **Card IDs**: `transactions.csv` does not have an explicit `card_id` string like `C01234-K1`. It has `customer_id` (e.g. `C06075`) and `card1`-`card6` features. However, the cases use `card_id` formats like `C01234-K1`. We will need to construct or map the exact string format for the graph out of `customer_id` and the specific card instance, or rely on mapping given in the case logs. Since `transactions.csv` missing an explicit `card_id` column is a common data challenge, we will derive a unique card identifier per customer based on the `card1`-`card6` attributes.
*   **Transactions**: Only online transactions (where `channel` = 'online' and `ProductCD` != 'W') have identity records. Inner joining transactions and identity might drop in-person transactions. Left joins must be used.
*   **Graph Nodes**: We must normalize strings, especially device profiles (`id_30`, `id_31`, `id_33`, `DeviceInfo`) to build accurate `DeviceProfile` vertices.

## Data Quality Observations
*   Lots of nulls in identity.csv and Vesta features (V, C, D, M columns).
*   Data represents a standard highly imbalanced fraud dataset structure.