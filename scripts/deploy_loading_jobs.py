"""
Deploy Loading Job Definitions to TigerGraph Savanna Cloud (fraud_investigation).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pyTigerGraph as tg


LOADING_JOBS = {
    "load_transactions": """
CREATE LOADING JOB load_transactions FOR GRAPH fraud_investigation {
  DEFINE FILENAME txn_file;
  DEFINE HEADER txn_header = "TransactionID", "ts", "TransactionAmt", "ProductCD",
    "channel", "addr1", "addr2", "risk_score",
    "P_emaildomain", "R_emaildomain", "customer_id", "card_id";

  LOAD txn_file
    TO VERTEX Customer VALUES ($"customer_id", $"ts", $"ts"),
    TO VERTEX Transaction VALUES (
       $"TransactionID", $"ts", $"TransactionAmt", $"ProductCD",
       $"channel", $"addr1", $"addr2", $"risk_score",
       $"P_emaildomain", $"R_emaildomain", $"customer_id", $"card_id"
    ),
    TO VERTEX BillingRegion VALUES ($"addr1", $"addr2") WHERE $"addr1" != "",
    TO VERTEX EmailDomain VALUES ($"P_emaildomain") WHERE $"P_emaildomain" != "",
    TO VERTEX EmailDomain VALUES ($"R_emaildomain") WHERE $"R_emaildomain" != "",
    TO EDGE BILLED_IN VALUES ($"TransactionID", $"addr1") WHERE $"addr1" != "",
    TO EDGE PURCHASER_EMAIL VALUES ($"TransactionID", $"P_emaildomain") WHERE $"P_emaildomain" != "",
    TO EDGE RECIPIENT_EMAIL VALUES ($"TransactionID", $"R_emaildomain") WHERE $"R_emaildomain" != ""
  USING SEPARATOR=",", HEADER="true", EOL="\\n", USER_DEFINED_HEADER="txn_header";
}
""",
    "load_cards": """
CREATE LOADING JOB load_cards FOR GRAPH fraud_investigation {
  DEFINE FILENAME card_file;
  DEFINE HEADER card_header = "card_id", "customer_id", "card4", "card6";

  LOAD card_file
    TO VERTEX Card VALUES ($"card_id", $"customer_id", $"card4", $"card6"),
    TO EDGE OWNS VALUES ($"customer_id", $"card_id")
  USING SEPARATOR=",", HEADER="true", EOL="\\n", USER_DEFINED_HEADER="card_header";
}
""",
    "load_made_edges": """
CREATE LOADING JOB load_made_edges FOR GRAPH fraud_investigation {
  DEFINE FILENAME made_file;
  DEFINE HEADER made_header = "card_id", "TransactionID";

  LOAD made_file
    TO EDGE MADE VALUES ($"card_id", $"TransactionID")
  USING SEPARATOR=",", HEADER="true", EOL="\\n", USER_DEFINED_HEADER="made_header";
}
""",
    "load_identity": """
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
""",
    "load_closed_cases": """
CREATE LOADING JOB load_closed_cases FOR GRAPH fraud_investigation {
  DEFINE FILENAME cc_file;
  DEFINE HEADER cc_header = "case_id", "customer_id", "card_id",
       "opened_at", "closed_at", "outcome", "pattern",
       "exposure_usd", "n_txns", "report_filed", "analyst_notes";

  LOAD cc_file
    TO VERTEX ClosedCase VALUES (
       $"case_id", $"customer_id", $"card_id",
       $"opened_at", $"closed_at", $"outcome", $"pattern",
       $"exposure_usd", $"n_txns", gsql_to_bool($"report_filed"), $"analyst_notes"
    ),
    TO EDGE CC_ON_CARD VALUES ($"case_id", $"card_id")
  USING SEPARATOR=",", HEADER="true", EOL="\\n", USER_DEFINED_HEADER="cc_header";
}
"""
}


def get_conn():
    host = os.environ["TG_HOST"].strip()
    raw_host = host
    if raw_host.startswith("https://"):
        raw_host = host[8:]
    elif raw_host.startswith("http://"):
        raw_host = host[7:]
    raw_host = raw_host.split(":")[0].split("/")[0]

    conn = tg.TigerGraphConnection(
        host=f"https://{raw_host}",
        graphname=os.environ.get("TG_GRAPH", "fraud_investigation"),
        gsqlSecret=os.environ.get("TG_SECRET", ""),
        tgCloud=True,
        sslPort=os.environ.get("TG_PORT", "443"),
    )
    conn.getToken(os.environ["TG_SECRET"])
    return conn


def deploy_loading_jobs():
    conn = get_conn()
    print("=" * 60)
    print("DEPLOYING LOADING JOBS TO fraud_investigation")
    print("=" * 60)

    results = {}
    for jname, jdef in LOADING_JOBS.items():
        print(f"Deploying loading job: {jname:24} ...", end=" ", flush=True)
        # Drop existing job if already present, then create
        drop_cmd = f"USE GRAPH fraud_investigation\nDROP JOB {jname}"
        conn.gsql(drop_cmd)
        create_cmd = f"USE GRAPH fraud_investigation\n{jdef}"
        out = conn.gsql(create_cmd)
        if "Successfully created" in out:
            print("OK (Created)")
            results[jname] = "DEPLOYED"
        else:
            print(f"OUTPUT: {out.strip()[:100]}")
            results[jname] = out.strip()

    print("-" * 60)
    print("Deployed loading jobs summary:")
    for k, v in results.items():
        print(f"  {k:24} -> {v}")

    # Verify listing of jobs in graph
    print("\nVerifying jobs on instance:")
    ls_out = conn.gsql("USE GRAPH fraud_investigation\nls")
    for line in ls_out.split("\n"):
        if "Jobs:" in line or "load_" in line:
            print(" ", line)

    return results


if __name__ == "__main__":
    deploy_loading_jobs()
