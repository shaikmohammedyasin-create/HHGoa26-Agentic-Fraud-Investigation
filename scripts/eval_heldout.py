"""
Held-out evaluation harness (fixed seed 20261030).

What it measures, on the synthetic evaluation set only (all eval data is
regenerable with scripts/make_synthetic_data.py - no third-party data):

  A. Deterministic engine fidelity across the 20 case-pack cases:
     verdict / pattern / exposure agreement vs cases/ground_truth.json.
  B. Risk-threshold-only baseline: label by the trigger risk_score alone,
     sweep thresholds 0.35..0.75, report best F1.
  C. Plain-LLM-no-graph baseline: one Nano prompt per case with flat
     transaction history (no device-sharing or graph-evidence features) -
     shows what knowledge-graph evidence adds over a bare LLM.
  D. Model/engine ablation across the 20 cases: how often the Nemotron
     pattern proposal agreed with the deterministic policy engine
     ("propose/decide" separation measured on real runs).
  E. Token Factory cost and latency per case from the JSONL call log.

Writes artifacts/eval_heldout.json and prints a human summary table.
Docs: keep only verified numbers; copy them into docs/BENCHMARK.md.

Usage:
    python scripts/eval_heldout.py            # full run (uses the API key)
    python scripts/eval_heldout.py --skip-llm # skip part C/D (no key needed)
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

# Make `backend` importable when run from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings                      # noqa: E402
from backend import db as app_db                         # noqa: E402
from backend.evaluation.exporter import case_to_answer   # noqa: E402
from backend.llm import nebius_client                    # noqa: E402

EVAL_SEED = 20261030
N_SAMPLE = 200
ROOT = Path(__file__).resolve().parents[1]
GT_PATH = ROOT / "cases" / "ground_truth.json"
SYNTH = ROOT / "data" / "synthetic"
OUT_PATH = ROOT / "artifacts" / "eval_heldout.json"

RISK_THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def stratified_closed_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Fixed-seed stratified sample by outcome label."""
    rng = random.Random(seed)
    by_outcome: dict[str, list[dict]] = {}
    for r in rows:
        by_outcome.setdefault(r.get("outcome", "?"), []).append(r)
    for bucket in by_outcome.values():
        rng.shuffle(bucket)
    return rng.sample(rows, min(n, len(rows)))


def _f1(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    p = tp / (tp + fp)
    r = tp / (tp + fn)
    return 2 * p * r / (p + r)


def part_a_engine_fidelity() -> dict:
    """Compare stored deterministic answers for the 20 case-pack cases."""
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    per_case = []
    for case_id, label in gt.items():
        payload = app_db.load_investigation(case_id)
        if not payload:
            per_case.append({"case_id": case_id, "label": label,
                             "engine": None, "verdict_ok": False,
                             "pattern_ok": False})
            continue
        engine_verdict = str(payload.get("verdict"))
        engine_pattern = str(payload.get("pattern"))
        per_case.append({
            "case_id": case_id,
            "label": label,
            "engine": {"verdict": engine_verdict, "pattern": engine_pattern},
            "verdict_ok": engine_verdict == label.get("verdict"),
            "pattern_ok": engine_pattern == label.get("pattern"),
        })
    n = len(per_case)
    return {
        "n_cases": n,
        "verdict_accuracy": round(sum(c["verdict_ok"] for c in per_case) / n, 4),
        "pattern_accuracy": round(sum(c["pattern_ok"] for c in per_case) / n, 4),
        "per_case": per_case,
    }


def part_b_risk_baseline(case_pack: list[dict], gt: dict) -> dict:
    """Label by trigger risk_score alone; sweep thresholds for best F1."""
    rows = []
    for row in case_pack:
        case_id = row["case_id"]
        if case_id not in gt or gt[case_id].get("verdict") not in {"fraud", "legitimate"}:
            continue
        rows.append((case_id, float(row["risk_score"]),
                     1 if gt[case_id]["verdict"] == "fraud" else 0))
    sweep = []
    for th in RISK_THRESHOLDS:
        tp = sum(1 for _, s, y in rows if s >= th and y == 1)
        fp = sum(1 for _, s, y in rows if s >= th and y == 0)
        fn = sum(1 for _, s, y in rows if s < th and y == 1)
        sweep.append({"threshold": th, "tp": tp, "fp": fp, "fn": fn,
                      "f1": round(_f1(tp, fp, fn), 4)})
    best = max(sweep, key=lambda s: s["f1"]) if sweep else {"f1": 0.0}
    return {"n": len(rows), "sweep": sweep, "best": best}


def part_c_plain_llm_baseline(case_pack: list[dict], transactions: list[dict],
                             gt: dict) -> dict:
    """One Nano prompt per case, flat history only - no graph evidence."""
    if not nebius_client.available():
        return {"n": 0, "note": "NEBIUS_API_KEY not set - run with the key "
                                "to measure the plain-LLM baseline."}

    txn_by_card: dict[str, list[dict]] = {}
    for t in transactions:
        txn_by_card.setdefault(t.get("card_id", ""), []).append(t)
    for txns in txn_by_card.values():
        txns.sort(key=lambda t: t.get("timestamp") or t.get("ts") or "")

    results = []
    for row in case_pack:
        case_id = row["case_id"]
        label = gt.get(case_id)
        if not label or label.get("verdict") not in {"fraud", "legitimate"}:
            continue
        card = row["card_id"]
        history = txn_by_card.get(card, [])[-12:]
        # Flat, non-graph facts only: raw txn list. No device-sharing counts,
        # no connected cards, no prior-case memories.
        flat = [{"ts": t.get("timestamp") or t.get("ts"),
                 "amount": t.get("amount"), "channel": t.get("channel"),
                 "merchant": t.get("merchant_id") or t.get("merchant")}
                for t in history]
        prompt = ("ORDER VERDICT NO-GRAPH BASELINE.\n"
                  "Assess ONLY the flat transaction history of one payment card.\n"
                  "You may NOT query any graph e.g. device sharing / prior cases.\n"
                  "Return JSON {\"verdict\": \"fraud\"|\"legitimate\", \"confidence\": 0..1}")
        raw = nebius_client.chat(
            role="baseline_plain_llm",
            system=prompt,
            user=json.dumps(flat, ensure_ascii=False),
            model=nebius_client.model_nano(),
            max_tokens=2048,
        )
        verdict = None
        if raw and raw[0]:
            import re
            match = re.search(r'"verdict"\s*:\s*"(fraud|legitimate)"', raw[0])
            verdict = match.group(1) if match else None
        results.append({
            "case_id": case_id,
            "label": label.get("verdict"),
            "baseline": verdict,
            "ok": verdict == label.get("verdict"),
        })
    n = len(results)
    ok = sum(1 for r in results if r["ok"])
    return {"n": n, "accuracy": round(ok / n, 4) if n else None,
            "per_case": results}


def part_d_ablation() -> dict:
    """Propose/decide agreement across the stored 20 runs."""
    agreed = disagree = missing = no_proposal = 0
    for case_id in json.loads(GT_PATH.read_text(encoding="utf-8")):
        payload = app_db.load_investigation(case_id)
        if not payload:
            missing += 1
            continue
        if payload.get("model_proposal"):
            if payload.get("model_agreed"):
                agreed += 1
            else:
                disagree += 1
        else:
            no_proposal += 1
    total = agreed + disagree
    return {"n_evaluated": agreed + disagree + no_proposal,
            "model_agreed": agreed, "engine_overruled_model": disagree,
            "no_model_proposal": no_proposal,
            "agreement_rate": round(agreed / total, 4) if total else None,
            "override_rate": round(disagree / total, 4) if total else None}


def part_e_cost_latency() -> dict:
    from backend.llm.nebius_client import log_summary
    s = log_summary()
    return {k: s[k] for k in ("available", "calls_logged", "successes",
                              "failures", "prompt_tokens_total",
                              "completion_tokens_total", "latency_ms_p50",
                              "latency_ms_p95", "by_role")}


def main(skip_llm: bool) -> int:
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    case_pack = _read_csv(SYNTH / "case_pack.csv")
    transactions = _read_csv(SYNTH / "transactions.csv")

    closed = _read_csv(SYNTH / "closed_cases_history.csv")
    stratified = stratified_closed_sample(closed, N_SAMPLE, EVAL_SEED)

    report = {
        "seed": EVAL_SEED,
        "closed_history_rows": len(closed),
        "stratified_sample_n": len(stratified),
        "note": ("The 28-case synthetic closed-case history is stratified at "
                 "fixed seed 20261030; per CC-* case full-pipeline runs run "
                 "through the same 20-case case-pack benchmark."),
        "engine_fidelity": part_a_engine_fidelity(),
        "risk_threshold_baseline": part_b_risk_baseline(case_pack, gt),
        "ablation_propose_decide": part_d_ablation(),
        "cost_latency": part_e_cost_latency(),
    }
    if not skip_llm:
        report["plain_llm_baseline"] = part_c_plain_llm_baseline(
            case_pack, transactions, gt)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    ef = report["engine_fidelity"]
    print()
    print("A. engine fidelity      verdict "
          f"{ef['verdict_accuracy']*100:.0f}%  pattern "
          f"{ef['pattern_accuracy']*100:.0f}%")
    rb = report["risk_threshold_baseline"]["best"]
    print(f"B. risk-only baseline   best F1 {rb.get('f1')} at threshold {rb.get('threshold')} "
          f"(n={report['risk_threshold_baseline']['n']})")
    ab = report["ablation_propose_decide"]
    print(f"D. propose/decide       model agreed {ab['model_agreed']}, "
          f"engine overruled {ab['engine_overruled_model']}, "
          f"agreement {ab['agreement_rate']}")
    cl = report["cost_latency"]
    print(f"E. cost/latency         {cl['successes']} ok calls, "
          f"p50 {cl['latency_ms_p50']} ms, p95 {cl['latency_ms_p95']} ms, "
          f"tokens in {cl['prompt_tokens_total']}, out {cl['completion_tokens_total']}")
    if "plain_llm_baseline" in report:
        pl = report["plain_llm_baseline"]
        print(f"C. plain-LLM (no graph) accuracy {pl.get('accuracy')} (n={pl.get('n')}) "
              "- see what graph evidence adds over a bare LLM")
    print(f"\nFull report written to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    skip = "--skip-llm" in sys.argv
    sys.exit(main(skip))
