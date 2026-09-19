import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()
res = conn.runLoadingJobWithFile(
    filePath=str(ROOT / "scratch" / "smoke_closed_cases.csv"),
    fileTag="cc_file",
    jobName="load_closed_cases"
)
print("Result load_closed_cases:", res)
