import sqlite3
import pandas as pd
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()

# Find cards that have device transactions in smoke_transactions
df_txns = pd.read_csv(ROOT / "scratch" / "smoke_transactions.csv")
df_id = pd.read_csv(ROOT / "scratch" / "smoke_identity.csv")
merged = pd.merge(df_txns, df_id, on="TransactionID")
print("Cards with identity transactions in smoke sample:")
card_counts = merged["card_id"].value_counts()
print(card_counts.head(5))

if len(card_counts) > 0:
    test_card = card_counts.index[0]
    print(f"\nTesting card_device_history on card with devices: {test_card}")
    res = conn.runInstalledQuery("card_device_history", {"card": test_card})
    print("Devices found:", len(res[0].get("devices", [])) if res else 0)
    print("Sample device:", res[0].get("devices", [])[:1] if res else None)
