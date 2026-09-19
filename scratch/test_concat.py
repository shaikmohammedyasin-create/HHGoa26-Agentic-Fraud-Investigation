import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()
cmd = """
USE GRAPH fraud_investigation
DROP JOB test_concat
CREATE LOADING JOB test_concat FOR GRAPH fraud_investigation {
  DEFINE FILENAME f;
  LOAD f TO VERTEX EmailDomain VALUES(gsql_concat($0, "_", $1)) USING SEPARATOR=",";
}
"""
print(conn.gsql(cmd))
res = conn.runLoadingJobWithFile(
    filePath=str(ROOT / "scratch" / "smoke_made.csv"),
    fileTag="f",
    jobName="test_concat"
)
print("Result:", res)
conn.gsql("USE GRAPH fraud_investigation\nDROP JOB test_concat")
