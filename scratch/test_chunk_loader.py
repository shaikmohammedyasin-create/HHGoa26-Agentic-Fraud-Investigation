import sys
import time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()

def load_file_chunked(conn, file_path, file_tag, job_name, chunk_size=50000):
    start_t = time.time()
    total_valid_lines = 0
    total_rejected = 0
    chunk_idx = 0
    tmp_path = ROOT / "scratch" / f"tmp_{job_name}.csv"

    print(f"Loading {file_path.name} in chunks of {chunk_size:,}...")
    for chunk in pd.read_csv(file_path, chunksize=chunk_size):
        chunk_idx += 1
        t_chunk = time.time()
        chunk.to_csv(tmp_path, index=False)
        res = conn.runLoadingJobWithFile(
            filePath=str(tmp_path),
            fileTag=file_tag,
            jobName=job_name,
            timeout=180000
        )
        if isinstance(res, list) and len(res) > 0:
            p_stats = res[0].get("statistics", {}).get("parsingStatistics", {})
            f_lvl = p_stats.get("fileLevel", {})
            v_lines = f_lvl.get("validLine", 0)
            r_lines = f_lvl.get("rejectLine", 0)
            total_valid_lines += (v_lines - 1)  # subtract 1 for header
            total_rejected += r_lines
            print(f"  Chunk {chunk_idx:2d} ({len(chunk):,} rows) loaded in {time.time() - t_chunk:.2f}s | valid={v_lines:,}, rej={r_lines}")
        else:
            print(f"  Chunk {chunk_idx:2d} response:", res)

    if tmp_path.exists():
        tmp_path.unlink()

    elapsed = time.time() - start_t
    print(f"  Total: {total_valid_lines:,} data rows loaded in {elapsed:.2f}s")
    return {"total_valid": total_valid_lines, "total_rejected": total_rejected, "elapsed": elapsed}

if __name__ == "__main__":
    # Test on closed cases (5,565 rows in 1 chunk)
    res = load_file_chunked(
        conn,
        ROOT / "data" / "full_load_staging" / "full_closed_cases.csv",
        "cc_file",
        "load_closed_cases",
        chunk_size=10000
    )
    print("Result:", res)
