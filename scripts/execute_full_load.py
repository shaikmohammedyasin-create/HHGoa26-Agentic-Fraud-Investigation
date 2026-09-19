"""
Full Dataset Execution Loader for TigerGraph Savanna Cloud (fraud_investigation).

SAFETY GUARD:
Requires --confirm-full-load flag to execute.
DO NOT RUN UNLESS EXPLICITLY APPROVED BY USER.
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pyTigerGraph as tg
from scripts.smoke_test_load import get_conn


DATA_DIR = ROOT / "data" / "full_load_staging"


def run_full_load():
    parser = argparse.ArgumentParser(description="Full TigerGraph Savanna dataset loader")
    parser.add_argument("--confirm-full-load", action="store_true", help="Explicit confirmation flag")
    args = parser.parse_args()

    if not args.confirm_full_load:
        print("ERROR: Safety lock engaged. You must provide '--confirm-full-load' to run the full dataset load.")
        sys.exit(1)

    print("=" * 60)
    print("STARTING FULL DATASET LOAD (590,742 TRANSACTIONS)")
    print("=" * 60)

    conn = get_conn()
    start_time = time.time()
    job_stats = {}

    def load_file_chunked(file_path, file_tag, job_name, chunk_size=50000):
        t0 = time.time()
        print(f"\n[{job_name}] Loading {file_path.name} (chunk size: {chunk_size:,})...", flush=True)
        tmp_path = ROOT / "scratch" / f"tmp_{job_name}.csv"
        total_valid_lines = 0
        total_rejected = 0
        total_obj_valid = {}
        total_obj_invalid = {}
        chunk_idx = 0

        for chunk in pd.read_csv(file_path, chunksize=chunk_size):
            chunk_idx += 1
            t_chunk = time.time()
            chunk.to_csv(tmp_path, index=False)
            res = None
            max_retries = 4
            for attempt in range(1, max_retries + 1):
                try:
                    res = conn.runLoadingJobWithFile(
                        filePath=str(tmp_path),
                        fileTag=file_tag,
                        jobName=job_name,
                        timeout=300000
                    )
                    break
                except Exception as ex:
                    print(f"  Chunk {chunk_idx:2d} attempt {attempt} error: {ex}. Retrying in 5s...", flush=True)
                    time.sleep(5)
                    if attempt == max_retries:
                        raise ex
            if isinstance(res, list) and len(res) > 0:
                p_stats = res[0].get("statistics", {}).get("parsingStatistics", {})
                f_lvl = p_stats.get("fileLevel", {})
                v_lines = f_lvl.get("validLine", 0)
                r_lines = f_lvl.get("rejectLine", 0)
                # v_lines includes 1 header row
                data_lines = max(0, v_lines - 1)
                total_valid_lines += data_lines
                total_rejected += r_lines

                # Aggregate object level stats
                for v in p_stats.get("objectLevel", {}).get("vertex", []):
                    vt = v.get("typeName")
                    total_obj_valid[vt] = total_obj_valid.get(vt, 0) + v.get("validObject", 0)
                    total_obj_invalid[vt] = total_obj_invalid.get(vt, 0) + v.get("invalidAttribute", 0)
                for e in p_stats.get("objectLevel", {}).get("edge", []):
                    et = e.get("typeName")
                    total_obj_valid[et] = total_obj_valid.get(et, 0) + e.get("validObject", 0)
                    total_obj_invalid[et] = total_obj_invalid.get(et, 0) + e.get("invalidAttribute", 0)

                print(f"  Chunk {chunk_idx:2d} ({len(chunk):,} rows) in {time.time() - t_chunk:.2f}s | valid={data_lines:,}, rej={r_lines}", flush=True)
            else:
                print(f"  Chunk {chunk_idx:2d} unexpected response: {res}", flush=True)

        if tmp_path.exists():
            tmp_path.unlink()

        elapsed = time.time() - t0
        print(f"  [{job_name}] Total: {total_valid_lines:,} data rows processed in {elapsed:.2f}s (rejections: {total_rejected})", flush=True)
        for k, v in total_obj_valid.items():
            print(f"    -> {k:18}: valid={v:,}, invalidAttr={total_obj_invalid.get(k, 0):,}", flush=True)

        job_stats[job_name] = {
            "processed_rows": total_valid_lines + total_rejected,
            "successful_rows": total_valid_lines,
            "rejected_rows": total_rejected,
            "object_valid": total_obj_valid,
            "object_invalid": total_obj_invalid,
            "duration": elapsed
        }

    import pandas as pd

    # 1. Cards (14,850 rows)
    load_file_chunked(DATA_DIR / "full_cards.csv", "card_file", "load_cards", chunk_size=20000)

    # 2. Made edges (590,742 rows)
    load_file_chunked(DATA_DIR / "full_made.csv", "made_file", "load_made_edges", chunk_size=50000)

    # 3. Transactions (590,742 rows)
    load_file_chunked(DATA_DIR / "full_transactions.csv", "txn_file", "load_transactions", chunk_size=50000)

    # 4. Identity (144,432 rows)
    load_file_chunked(DATA_DIR / "full_identity.csv", "id_file", "load_identity", chunk_size=50000)

    # 5. Closed cases (5,565 rows)
    load_file_chunked(DATA_DIR / "full_closed_cases.csv", "cc_file", "load_closed_cases", chunk_size=20000)

    total_elapsed = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print(f"ALL 5 JOBS COMPLETED IN {total_elapsed:.2f} SECONDS ({total_elapsed/60:.2f} MINUTES)", flush=True)
    print("=" * 60, flush=True)

    # Post-load verification counts
    print("\nLive Vertex Counts after full load:", flush=True)
    v_counts = conn.getVertexCount("*")
    for vname, cnt in sorted(v_counts.items()):
        print(f"  {vname:20}: {cnt:,}", flush=True)

    print("\nLive Edge Counts after full load:", flush=True)
    e_counts = {}
    for etype in [
        "OWNS", "MADE", "FROM_DEVICE", "PURCHASER_EMAIL", "RECIPIENT_EMAIL",
        "BILLED_IN", "CC_ON_CARD"
    ]:
        try:
            cnt = conn.getEdgeCount(etype)
            e_counts[etype] = cnt
            print(f"  {etype:20}: {cnt:,}", flush=True)
        except Exception as e:
            print(f"  {etype:20}: ERROR {e}", flush=True)

    return {
        "job_stats": job_stats,
        "total_elapsed": total_elapsed,
        "v_counts": v_counts,
        "e_counts": e_counts
    }


if __name__ == "__main__":
    run_full_load()
