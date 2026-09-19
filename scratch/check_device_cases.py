import sqlite3
import json
from pathlib import Path

def main():
    conn = sqlite3.connect("data/fraud.db")
    cursor = conn.cursor()
    
    for i in range(1, 21):
        case_id = f"HHG-{i:03d}"
        case_file = Path(f"cases/{case_id}.json")
        if not case_file.exists():
            continue
        case_data = json.loads(case_file.read_text(encoding="utf-8"))
        trigger = case_data.get("trigger") or {}
        txn_id = trigger.get("flagged_txn_id")
        if not txn_id:
            continue
        id_row = cursor.execute("SELECT DeviceInfo, id_30, id_31, id_33 FROM identity WHERE TransactionID=?", (txn_id,)).fetchone()
        if id_row and any(id_row):
            label = " | ".join(str(x or "unknown") for x in id_row)
            # check accounts sharing device
            parts = [p.strip() for p in label.split("|")]
            dev_info = parts[0]
            sharing = cursor.execute("""
                SELECT DISTINCT t.card_id, t.customer_id
                FROM identity i
                JOIN transactions t ON t.TransactionID = i.TransactionID
                WHERE COALESCE(i.DeviceInfo, 'unknown') = ?
                  AND COALESCE(i.id_30, 'unknown') = ?
                  AND COALESCE(i.id_31, 'unknown') = ?
                  AND COALESCE(i.id_33, 'unknown') = ?
                LIMIT 5
            """, (parts[0], parts[1], parts[2], parts[3])).fetchall()
            
            # check closed cases by device
            notes_cases = cursor.execute("SELECT case_id, outcome, pattern FROM closed_cases WHERE analyst_notes LIKE ? LIMIT 5", (f"%{dev_info}%",)).fetchall()
            
            print(f"{case_id} (txn {txn_id}):")
            print(f"  Device: {label}")
            print(f"  Accounts sharing device count: {len(sharing)} (sample: {sharing[:2]})")
            print(f"  Closed cases mentioning {dev_info}: {len(notes_cases)} (sample: {notes_cases[:2]})")

if __name__ == "__main__":
    main()
