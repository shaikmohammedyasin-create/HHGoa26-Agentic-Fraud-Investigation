import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.graph.tg_adapter import get_connection

def test_query_syntax():
    conn = get_connection()
    q1 = """
CREATE OR REPLACE QUERY test_dev_syntax(STRING dp) FOR GRAPH fraud_investigation {
  Seed = {to_vertex(dp, "DeviceProfile")};
  txns = SELECT t FROM Seed:s <-(FROM_DEVICE:e)- Transaction:t;
  PRINT txns;
}
"""
    print("Testing GSQL compilation for reverse traversal on FROM_DEVICE:")
    res = conn.gsql(f"USE GRAPH fraud_investigation\n{q1}")
    print("Response:")
    print(res)

if __name__ == "__main__":
    test_query_syntax()
