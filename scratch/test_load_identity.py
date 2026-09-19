import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.smoke_test_load import get_conn

conn = get_conn()
cmd = """
USE GRAPH fraud_investigation
DROP JOB load_identity
CREATE LOADING JOB load_identity FOR GRAPH fraud_investigation {
  DEFINE FILENAME id_file;
  DEFINE HEADER id_header = "TransactionID", "DeviceInfo", "id_30", "id_31", "id_33", "DeviceType";

  LOAD id_file
    TO VERTEX DeviceProfile VALUES (
       gsql_concat($"DeviceInfo", " | ", $"id_30", " | ", $"id_31", " | ", $"id_33"),
       $"DeviceInfo", $"id_30", $"id_31", $"id_33", $"DeviceType"
    ),
    TO EDGE FROM_DEVICE VALUES (
       $"TransactionID",
       gsql_concat($"DeviceInfo", " | ", $"id_30", " | ", $"id_31", " | ", $"id_33")
    )
  USING SEPARATOR=",", HEADER="true", EOL="\\n", USER_DEFINED_HEADER="id_header";
}
"""
print(conn.gsql(cmd))
res = conn.runLoadingJobWithFile(
    filePath=str(ROOT / "scratch" / "smoke_identity.csv"),
    fileTag="id_file",
    jobName="load_identity"
)
print("Result load_identity:", res)
