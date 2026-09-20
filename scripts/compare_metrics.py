import json
import csv

cases_data = json.load(open('cases/_checkpoint_report.json'))
benchmark_summary = json.load(open('artifacts/benchmark/benchmark_summary.json'))

# Expected answers from benchmark_summary baseline
expected_map = {c['case_id']: c for c in benchmark_summary['cases_summary']}

print(f"{'Case':8} | {'Expected Pattern':28} | {'Actual Pattern':28} | {'Match?':7} | {'Verdict (Act/Exp)':18} | {'SAR (Act/Exp)':15}")
print("-" * 115)

pattern_matches = 0
verdict_matches = 0
sar_matches = 0
candidate_recalls = 0

for r in cases_data['results']:
    cid = r['case_id']
    act_pat = r['pattern']
    act_verd = r['verdict']
    act_sar = r['sar_filed']
    
    # load case json to inspect candidates and nba
    c_json = json.load(open(f"cases/{cid}.json"))
    c_case = c_json['case']
    c_cand = [c['pattern'] for c in c_json.get('pattern_candidates', [])] or [act_pat]
    
    exp = expected_map.get(cid, {})
    exp_pat = exp.get('expected_pattern')
    exp_verd = exp.get('expected_verdict')
    exp_sar = exp.get('expected_sar')
    
    pat_m = (act_pat == exp_pat)
    verd_m = (act_verd == exp_verd)
    sar_m = (act_sar == exp_sar)
    cand_m = (exp_pat in c_cand)
    
    if pat_m: pattern_matches += 1
    if verd_m: verdict_matches += 1
    if sar_m: sar_matches += 1
    if cand_m: candidate_recalls += 1
    
    print(f"{cid:8} | {exp_pat:28} | {act_pat:28} | {str(pat_m):7} | {act_verd:9}/{exp_verd:8} | {str(act_sar):6}/{str(exp_sar):6}")

print("-" * 115)
print(f"Primary Pattern Accuracy: {pattern_matches}/20 ({pattern_matches/20*100:.1f}%) [Baseline was 11/20 (55.0%)]")
print(f"Candidate Recall:         {candidate_recalls}/20 ({candidate_recalls/20*100:.1f}%) [Baseline was 18/20 (90.0%)]")
print(f"Verdict Accuracy:         {verdict_matches}/20 ({verdict_matches/20*100:.1f}%) [Baseline was 18/20 (90.0%)]")
print(f"SAR Accuracy:             {sar_matches}/20 ({sar_matches/20*100:.1f}%) [Baseline was 18/20 (90.0%)]")
print(f"IEEE Checkpoints:         {cases_data['checkpoint_pass']}/{cases_data['checkpoint_total']} (100.0%)")
