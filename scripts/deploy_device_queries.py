import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.graph.tg_adapter import get_connection

DEVICE_NEIGHBORS_GSQL = """
CREATE OR REPLACE QUERY device_neighbors(STRING dp, INT limit_n = 20) FOR GRAPH fraud_investigation {
  AllTxns = {Transaction.*};
  dev_txns = SELECT t FROM AllTxns:t -(FROM_DEVICE:e)-> DeviceProfile:d
             WHERE d == to_vertex(dp, "DeviceProfile") OR d.device_info == dp;
  cards = SELECT c FROM dev_txns:t -(MADE_BY:e)-> Card:c
          LIMIT limit_n;
  PRINT cards AS result;
}
"""

CASES_BY_DEVICE_GSQL = """
CREATE OR REPLACE QUERY cases_by_device(STRING device_label, INT limit_n = 10) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc FROM AllCases:cc
    WHERE cc.analyst_notes LIKE ("%" + device_label + "%")
    ORDER BY cc.closed_at DESC
    LIMIT limit_n;
  PRINT cases AS result;
}
"""

def deploy_queries():
    conn = get_connection()
    print("=" * 60)
    print("DEPLOYING P0 REMEDIATION QUERIES TO fraud_investigation")
    print("=" * 60)

    # 1. Create queries
    print("1. Creating device_neighbors query...")
    res1 = conn.gsql(f"USE GRAPH fraud_investigation\n{DEVICE_NEIGHBORS_GSQL}")
    print(res1)

    print("2. Creating cases_by_device query...")
    res2 = conn.gsql(f"USE GRAPH fraud_investigation\n{CASES_BY_DEVICE_GSQL}")
    print(res2)

    # 2. Install queries
    print("\n3. Installing queries: device_neighbors, cases_by_device ...")
    install_res = conn.gsql("USE GRAPH fraud_investigation\nINSTALL QUERY device_neighbors, cases_by_device")
    print("Install Output:")
    print(install_res)

    # 3. Test queries live
    print("\n4. Testing live execution of device_neighbors...")
    test_dp = "iOS Device | iOS 9.3.5 | mobile safari 9.0 | 1024x768"
    out_dn = conn.runInstalledQuery("device_neighbors", {"dp": test_dp, "limit_n": 5})
    print("device_neighbors result:", out_dn)

    print("\n5. Testing live execution of cases_by_device...")
    out_cbd = conn.runInstalledQuery("cases_by_device", {"device_label": "Windows", "limit_n": 5})
    print("cases_by_device result count:", len(out_cbd[0].get("result", [])) if out_cbd else 0)

if __name__ == "__main__":
    deploy_queries()
