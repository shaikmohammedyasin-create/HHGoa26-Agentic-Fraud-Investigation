import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()

print("--- Query 1: txn_device ---")
# Find a txn that has identity / device
import pandas as pd
df_id = pd.read_csv(ROOT / "scratch" / "smoke_identity.csv")
sample_txn = str(df_id.iloc[0]["TransactionID"])
print(f"Testing txn_device on txn {sample_txn}...")
try:
    r = conn.runInstalledQuery("txn_device", {"txn": sample_txn})
    print("  txn_device:", r)
except Exception as e:
    print("  txn_device err:", e)

print("\n--- Query 2: device_transactions ---")
try:
    # First get device profile id for sample_txn
    r_dev = conn.getEdges("Transaction", sample_txn, "FROM_DEVICE")
    print("  FROM_DEVICE edges:", r_dev)
    if r_dev:
        dev_id = r_dev[0]["to_id"]
        r_dt = conn.runInstalledQuery("device_transactions", {"dev": dev_id, "limit_n": 5})
        print(f"  device_transactions for {dev_id}:", r_dt)
except Exception as e:
    print("  device_transactions err:", e)

print("\n--- Query 3: recent_cases_for_card ---")
try:
    r_cc = conn.runInstalledQuery("recent_cases_for_card", {"card": "C12382-K1", "limit_n": 5})
    print("  recent_cases_for_card:", r_cc)
except Exception as e:
    print("  recent_cases_for_card err:", e)

print("\n--- Query 4: customer_summary ---")
try:
    r_cs = conn.runInstalledQuery("customer_summary", {"cust": "C12382"})
    print("  customer_summary:", r_cs)
except Exception as e:
    print("  customer_summary err:", e)

print("\n--- Query 5: count_card_transactions ---")
try:
    r_cnt = conn.runInstalledQuery("count_card_transactions", {"card": "C12382-K1"})
    print("  count_card_transactions:", r_cnt)
except Exception as e:
    print("  count_card_transactions err:", e)
