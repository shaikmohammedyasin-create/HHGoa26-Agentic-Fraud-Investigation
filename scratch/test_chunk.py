import sys
from pathlib import Path
import time
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()
print("Reading first 50,000 rows of full_made.csv...")
df_50k = pd.read_csv(ROOT / "data" / "full_load_staging" / "full_made.csv", nrows=50000)
test_chunk_path = ROOT / "scratch" / "test_chunk_made.csv"
df_50k.to_csv(test_chunk_path, index=False)

print("Testing runLoadingJobWithFile on 50,000 rows...")
t0 = time.time()
res = conn.runLoadingJobWithFile(
    filePath=str(test_chunk_path),
    fileTag="made_file",
    jobName="load_made_edges",
    timeout=300000
)
print(f"Completed in {time.time() - t0:.2f}s:")
print(res)
