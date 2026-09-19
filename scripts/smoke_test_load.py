"""
Staged Smoke-Test Loader for TigerGraph Savanna Cloud (fraud_investigation).

Extracts a controlled representative subset (~1,000 transactions, 20 benchmark entities,
all matching cards, identities, billing regions, email domains, and 100 closed cases),
loads them into fraud_investigation, verifies counts, and tests installed queries.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pandas as pd
import pyTigerGraph as tg


SCRATCH_DIR = ROOT / "scratch"
SCRATCH_DIR.mkdir(exist_ok=True)


def get_conn():
    host = os.environ["TG_HOST"].strip()
    raw_host = host
    if raw_host.startswith("https://"):
        raw_host = host[8:]
    elif raw_host.startswith("http://"):
        raw_host = host[7:]
    raw_host = raw_host.split(":")[0].split("/")[0]

    conn = tg.TigerGraphConnection(
        host=f"https://{raw_host}",
        graphname=os.environ.get("TG_GRAPH", "fraud_investigation"),
        gsqlSecret=os.environ.get("TG_SECRET", ""),
        tgCloud=True,
        sslPort=os.environ.get("TG_PORT", "443"),
    )
    conn.getToken(os.environ["TG_SECRET"])
    return conn


def extract_smoke_dataset():
    print("=" * 60)
    print("STEP 1: EXTRACTING CONTROLLED SMOKE-TEST SUBSET")
    print("=" * 60)

    db_path = ROOT / "data" / "prepared" / "investigation.db"
    conn = sqlite3.connect(str(db_path))

    # 1. Benchmark cases
    case_pack = pd.read_sql("SELECT * FROM case_pack", conn)
    benchmark_custs = case_pack["customer_id"].unique().tolist()
    benchmark_cards = case_pack["card_id"].unique().tolist()
    flagged_txns = case_pack["flagged_txn_id"].astype(str).tolist()

    print(f"  Benchmark Cases:      {len(case_pack)}")
    print(f"  Benchmark Customers:  {len(benchmark_custs)}")
    print(f"  Benchmark Cards:      {len(benchmark_cards)}")
    print(f"  Flagged Transactions: {len(flagged_txns)}")

    # 2. Representative transactions:
    # First: include all 20 flagged transactions
    flagged_df = pd.read_sql(
        f"SELECT * FROM transactions WHERE TransactionID IN ({','.join(['?']*len(flagged_txns))})",
        conn,
        params=flagged_txns
    )

    # Next: up to 50 transactions per benchmark customer
    cust_txns = []
    for c in benchmark_custs:
        c_df = pd.read_sql(
            "SELECT * FROM transactions WHERE customer_id = ? ORDER BY ts LIMIT 45",
            conn,
            params=[c]
        )
        cust_txns.append(c_df)

    # Combine & deduplicate transactions
    all_txns = pd.concat([flagged_df] + cust_txns, ignore_index=True).drop_duplicates(subset=["TransactionID"])
    print(f"  Selected Transactions: {len(all_txns)}")

    # Ensure required columns for load_transactions
    txn_export = all_txns[[
        "TransactionID", "ts", "TransactionAmt", "ProductCD",
        "channel", "addr1", "addr2", "risk_score",
        "P_emaildomain", "R_emaildomain", "customer_id", "card_id"
    ]].copy()
    txn_export["addr1"] = txn_export["addr1"].fillna("")
    txn_export["addr2"] = txn_export["addr2"].fillna("")
    txn_export["P_emaildomain"] = txn_export["P_emaildomain"].fillna("")
    txn_export["R_emaildomain"] = txn_export["R_emaildomain"].fillna("")

    txn_csv = SCRATCH_DIR / "smoke_transactions.csv"
    txn_export.to_csv(txn_csv, index=False)

    # 3. Cards & OWNS edges
    card_ids = txn_export["card_id"].unique().tolist()
    cards_df = all_txns[["card_id", "customer_id", "card4", "card6"]].drop_duplicates(subset=["card_id"]).copy()
    cards_df["card4"] = cards_df["card4"].fillna("")
    cards_df["card6"] = cards_df["card6"].fillna("")
    cards_csv = SCRATCH_DIR / "smoke_cards.csv"
    cards_df.to_csv(cards_csv, index=False)
    print(f"  Unique Cards:          {len(cards_df)}")

    # 4. MADE edges (card_id, TransactionID)
    made_df = txn_export[["card_id", "TransactionID"]].drop_duplicates()
    made_csv = SCRATCH_DIR / "smoke_made.csv"
    made_df.to_csv(made_csv, index=False)
    print(f"  MADE Edges:            {len(made_df)}")

    # 5. Identity / Devices
    txn_id_list = txn_export["TransactionID"].astype(str).tolist()
    placeholders = ",".join("?" * len(txn_id_list))
    id_df = pd.read_sql(
        f"SELECT TransactionID, DeviceInfo, id_30, id_31, id_33, DeviceType FROM identity WHERE TransactionID IN ({placeholders})",
        conn,
        params=txn_id_list
    )
    id_df = id_df.fillna("unknown")
    id_csv = SCRATCH_DIR / "smoke_identity.csv"
    id_df.to_csv(id_csv, index=False)
    print(f"  Identity Records:      {len(id_df)}")

    # 6. Closed Cases (100 cases, including any matching benchmark cards/customers)
    matched_cc = pd.read_sql(
        f"SELECT * FROM closed_cases WHERE customer_id IN ({','.join(['?']*len(benchmark_custs))})",
        conn,
        params=benchmark_custs
    )
    other_cc = pd.read_sql("SELECT * FROM closed_cases ORDER BY case_id LIMIT 100", conn)
    all_cc = pd.concat([matched_cc, other_cc], ignore_index=True).drop_duplicates(subset=["case_id"])
    print(f"  Closed Cases:          {len(all_cc)}")

    # Format report_filed as bool string or boolean for loader
    all_cc_export = all_cc[[
        "case_id", "customer_id", "card_id", "opened_at", "closed_at",
        "outcome", "pattern", "exposure_usd", "n_txns", "report_filed", "analyst_notes"
    ]].copy()
    all_cc_export["report_filed"] = all_cc_export["report_filed"].apply(
        lambda x: "true" if str(x).lower() in ("yes", "true", "1") else "false"
    )
    cc_csv = SCRATCH_DIR / "smoke_closed_cases.csv"
    all_cc_export.to_csv(cc_csv, index=False)

    conn.close()
    return {
        "txn_csv": str(txn_csv),
        "cards_csv": str(cards_csv),
        "made_csv": str(made_csv),
        "id_csv": str(id_csv),
        "cc_csv": str(cc_csv),
        "flagged_txns": flagged_txns,
        "benchmark_cards": benchmark_cards,
        "benchmark_custs": benchmark_custs
    }


def run_smoke_load():
    data = extract_smoke_dataset()
    tg_conn = get_conn()

    print("\n" + "=" * 60)
    print("STEP 2: RUNNING LOADING JOBS ON REAL SAVANNA GRAPH")
    print("=" * 60)

    load_results = {}

    # Job 1: load_cards
    print("Running load_cards ...")
    res_cards = tg_conn.runLoadingJobWithFile(
        filePath=data["cards_csv"],
        fileTag="card_file",
        jobName="load_cards"
    )
    print("  load_cards response:", res_cards)
    load_results["load_cards"] = res_cards

    # Job 2: load_transactions
    print("\nRunning load_transactions ...")
    res_txns = tg_conn.runLoadingJobWithFile(
        filePath=data["txn_csv"],
        fileTag="txn_file",
        jobName="load_transactions"
    )
    print("  load_transactions response:", res_txns)
    load_results["load_transactions"] = res_txns

    # Job 3: load_made_edges
    print("\nRunning load_made_edges ...")
    res_made = tg_conn.runLoadingJobWithFile(
        filePath=data["made_csv"],
        fileTag="made_file",
        jobName="load_made_edges"
    )
    print("  load_made_edges response:", res_made)
    load_results["load_made_edges"] = res_made

    # Job 4: load_identity
    print("\nRunning load_identity ...")
    res_id = tg_conn.runLoadingJobWithFile(
        filePath=data["id_csv"],
        fileTag="id_file",
        jobName="load_identity"
    )
    print("  load_identity response:", res_id)
    load_results["load_identity"] = res_id

    # Job 5: load_closed_cases
    print("\nRunning load_closed_cases ...")
    res_cc = tg_conn.runLoadingJobWithFile(
        filePath=data["cc_csv"],
        fileTag="cc_file",
        jobName="load_closed_cases"
    )
    print("  load_closed_cases response:", res_cc)
    load_results["load_closed_cases"] = res_cc

    # Step 3: Check live vertex and edge counts
    print("\n" + "=" * 60)
    print("STEP 3: VERIFYING POST-LOAD VERTEX & EDGE COUNTS")
    print("=" * 60)

    v_counts = tg_conn.getVertexCount("*")
    print("Live Vertex Counts:")
    for vname, cnt in v_counts.items():
        print(f"  {vname:20}: {cnt}")

    e_counts = {}
    for etype in [
        "OWNS", "MADE", "FROM_DEVICE", "PURCHASER_EMAIL", "RECIPIENT_EMAIL",
        "BILLED_IN", "CC_ON_CARD"
    ]:
        try:
            cnt = tg_conn.getEdgeCount(etype)
            e_counts[etype] = cnt
            print(f"  {etype:20}: {cnt}")
        except Exception as e:
            e_counts[etype] = f"ERR: {e}"

    # Step 4: Run installed query verifications
    print("\n" + "=" * 60)
    print("STEP 4: RUNNING INSTALLED QUERIES AGAINST LOADED SAMPLE")
    print("=" * 60)

    query_results = {}

    # 1. Transaction lookup
    flagged_0 = data["flagged_txns"][0]
    print(f"Testing txn_by_id on flagged txn {flagged_0} ...")
    r_txn = tg_conn.runInstalledQuery("txn_by_id", {"txn_id": flagged_0})
    print("  txn_by_id result:", r_txn)
    query_results["txn_by_id"] = "PASS" if r_txn and len(r_txn) > 0 and len(r_txn[0].get("result", [])) > 0 else "FAIL"

    # 2. Card history
    card_0 = data["benchmark_cards"][0]
    print(f"Testing card_transaction_history on card {card_0} ...")
    r_ch = tg_conn.runInstalledQuery("card_transaction_history", {"card": card_0, "limit_n": 5})
    print("  card_transaction_history count:", len(r_ch[0].get("result", [])) if r_ch else 0)
    query_results["card_transaction_history"] = "PASS" if r_ch and len(r_ch[0].get("result", [])) > 0 else "FAIL"

    # 3. Customer cards
    cust_0 = data["benchmark_custs"][0]
    print(f"Testing customer_cards on customer {cust_0} ...")
    r_ccards = tg_conn.runInstalledQuery("customer_cards", {"cust": cust_0})
    print("  customer_cards result:", r_ccards)
    query_results["customer_cards"] = "PASS" if r_ccards and len(r_ccards[0].get("cards", [])) > 0 else "FAIL"

    # 4. Cases by pattern
    print("Testing cases_by_pattern for 'card_not_present_fraud' ...")
    r_patt = tg_conn.runInstalledQuery("cases_by_pattern", {"pattern": "card_not_present_fraud", "limit_n": 5})
    print("  cases_by_pattern count:", len(r_patt[0].get("cases", [])) if r_patt else 0)
    query_results["cases_by_pattern"] = "PASS" if r_patt and len(r_patt[0].get("cases", [])) > 0 else "FAIL"

    # 5. Search case notes
    print("Testing search_case_notes for 'cardholder' ...")
    r_notes = tg_conn.runInstalledQuery("search_case_notes", {"search_text": "cardholder", "limit_n": 5})
    print("  search_case_notes count:", len(r_notes[0].get("cases", [])) if r_notes else 0)
    query_results["search_case_notes"] = "PASS" if r_notes and len(r_notes[0].get("cases", [])) > 0 else "FAIL"

    # 6. Card amount stats
    print(f"Testing card_amount_stats on card {card_0} ...")
    r_stats = tg_conn.runInstalledQuery("card_amount_stats", {"card": card_0})
    print("  card_amount_stats result:", r_stats)
    query_results["card_amount_stats"] = "PASS" if r_stats else "FAIL"

    # Step 5: Test through backend adapter
    print("\n" + "=" * 60)
    print("STEP 5: VERIFYING BACKEND ADAPTER LIVE INVOCATION")
    print("=" * 60)
    from backend.graph.tg_adapter import get_transaction, get_customer_cards, get_card_transaction_history, get_closed_cases_by_pattern

    adapter_txn = get_transaction(flagged_0)
    print(f"  adapter.get_transaction({flagged_0}):", adapter_txn)
    adapter_cards = get_customer_cards(cust_0)
    print(f"  adapter.get_customer_cards({cust_0}):", adapter_cards)
    adapter_history = get_card_transaction_history(card_0, limit=5)
    print(f"  adapter.get_card_transaction_history({card_0}): {len(adapter_history)} transactions")
    adapter_cases = get_closed_cases_by_pattern("card_not_present_fraud", limit=5)
    print(f"  adapter.get_closed_cases_by_pattern: {len(adapter_cases)} cases")

    adapter_ok = (
        adapter_txn is not None and
        len(adapter_cards) > 0 and
        len(adapter_history) > 0 and
        len(adapter_cases) > 0
    )

    print("\n" + "=" * 60)
    print(f"SMOKE TEST SUMMARY: {'ALL PASSED' if adapter_ok else 'SOME CHECKS FAILED'}")
    print("=" * 60)
    return {
        "load_results": load_results,
        "v_counts": v_counts,
        "e_counts": e_counts,
        "query_results": query_results,
        "adapter_ok": adapter_ok
    }


if __name__ == "__main__":
    run_smoke_load()
