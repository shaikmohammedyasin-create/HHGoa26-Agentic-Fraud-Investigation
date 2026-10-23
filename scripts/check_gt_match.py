# Quick check: benchmark results vs ground truth labels
import json

gt = json.load(open("cases/ground_truth.json"))
b = json.load(open("cases/_benchmark_report.json"))
bm = {r["case_id"]: r for r in b["results"]}

ok, bad = 0, []
for cid, want in sorted(gt.items()):
    r = bm.get(cid)
    if not r:
        bad.append((cid, "MISSING"))
        continue
    if (r["verdict"], r["pattern"]) == (want["verdict"], want["pattern"]):
        ok += 1
    else:
        bad.append((cid,
                    f"want={want['verdict']}/{want['pattern']}",
                    f"got={r['verdict']}/{r['pattern']} prob={r['fraud_probability']}"))

print(f"MATCHED {ok}/20")
for x in bad:
    print(*x)
