import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn
import pandas as pd

conn = get_conn()

df_id = pd.read_csv(ROOT / "scratch" / "smoke_identity.csv")
sample_txn = str(df_id.iloc[0]["TransactionID"])

print("1. Testing txn_device_profile on txn", sample_txn)
r1 = conn.runInstalledQuery("txn_device_profile", {"txn_id": sample_txn})
print("   txn_device_profile result:", r1)

print("\n2. Testing txn_identity on txn", sample_txn)
r2 = conn.runInstalledQuery("txn_identity", {"txn_id": sample_txn})
print("   txn_identity result:", r2)

print("\n3. Testing card_closed_cases on card C12382-K1")
r3 = conn.runInstalledQuery("card_closed_cases", {"card": "C12382-K1"})
print("   card_closed_cases result:", r3)

print("\n4. Testing customer_closed_cases on customer C12382")
r4 = conn.runInstalledQuery("customer_closed_cases", {"cust": "C12382"})
print("   customer_closed_cases result:", r4)

print("\n5. Testing card_device_history on card C12382-K1")
r5 = conn.runInstalledQuery("card_device_history", {"card": "C12382-K1"})
print("   card_device_history count:", len(r5[0].get("devices", [])) if r5 else 0)
