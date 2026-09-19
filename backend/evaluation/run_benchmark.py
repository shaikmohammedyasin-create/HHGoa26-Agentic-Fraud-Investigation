"""
Benchmark runner.

Runs all 20 case-pack cases through the investigation pipeline
and writes answer files + a summary report.

Usage:
    python -m backend.evaluation.run_benchmark
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings
from backend.logging import configure_logging, get_logger
from backend.agents.orchestrator import run_investigation
from backend.evaluation.exporter import write_answer_file, case_to_answer
from backend.graph import query_router as graph

configure_logging()
log = get_logger(__name__)


def run_all() -> dict:
    """Run the full 20-case benchmark."""
    triggers = graph.get_all_case_triggers()
    if not triggers:
        log.error("benchmark.no_triggers",
                  hint="Run python -m backend.scripts.prepare_data first")
        return {"error": "No case triggers found"}

    log.info("benchmark.start", n_cases=len(triggers))
    t0 = time.time()

    results: list[dict] = []
    errors: list[dict] = []

    for row in triggers:
        case_id = str(row["case_id"])
        log.info("benchmark.case.start", case_id=case_id)
        try:
            # force=True: a benchmark run must always reflect the current
            # pipeline rather than a cached earlier result.
            case = run_investigation(case_id, force=True)
            write_answer_file(case)
            answer = case_to_answer(case)
            results.append({
                "case_id": case_id,
                "verdict": case.verdict.value,
                "fraud_probability": round(case.fraud_probability, 3),
                "pattern": case.pattern.value,
                "status": case.status.value,
                "exposure_usd": round(case.exposure_usd, 2),
                "evidence_count": len(case.evidence),
                "tool_calls": case.tool_calls,
                "latency_s": case.latency_s,
                "sar_filed": case.sar.file,
                "nba_initial_count": len(case.nba_initial),
                "nba_final_count": len(case.nba_final),
                "stop_reason": case.stop_reason[:120],
            })
            log.info("benchmark.case.complete", case_id=case_id,
                     verdict=case.verdict.value, prob=case.fraud_probability)
        except Exception as exc:
            log.exception("benchmark.case.error", case_id=case_id, error=str(exc))
            errors.append({"case_id": case_id, "error": str(exc)})

    elapsed = round(time.time() - t0, 1)

    report = {
        "total_cases": len(triggers),
        "completed": len(results),
        "failed": len(errors),
        "elapsed_s": elapsed,
        "results": results,
        "errors": errors,
    }

    # Write report
    report_path = settings.cases_dir / "_benchmark_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("benchmark.complete", completed=len(results), failed=len(errors),
             elapsed_s=elapsed, report=str(report_path))

    return report


if __name__ == "__main__":
    report = run_all()
    print(json.dumps(report, indent=2))
