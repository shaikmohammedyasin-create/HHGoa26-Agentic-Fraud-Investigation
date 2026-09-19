import json
from pathlib import Path

cases_dir = Path("cases")
print(f"{'Case':<8} | {'Verdict':<11} | {'Pattern':<27} | {'Prob':<5} | {'Status':<17} | {'SAR':<5} | {'Ev'}")
print("-" * 80)
for p in sorted(cases_dir.glob("HHG-*.json")):
    data = json.loads(p.read_text(encoding="utf-8"))
    cid = data.get("case_id")
    c = data.get("case", {})
    sar = data.get("sar", {}).get("file", False)
    ev_cnt = len(c.get("evidence", []))
    print(f"{cid:<8} | {c.get('verdict',''):<11} | {c.get('pattern',''):<27} | {c.get('fraud_probability',0):<5} | {c.get('status',''):<17} | {str(sar):<5} | {ev_cnt}")
