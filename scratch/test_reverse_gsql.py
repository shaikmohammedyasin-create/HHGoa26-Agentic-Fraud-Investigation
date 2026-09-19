import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.graph.tg_adapter import get_connection

def main():
    conn = get_connection()
    q = """
CREATE OR REPLACE QUERY test_str_dp(STRING dp, INT limit_n = 20) FOR GRAPH fraud_investigation {
  AllTxns = {Transaction.*};
  dev_txns = SELECT t FROM AllTxns:t -(FROM_DEVICE:e)-> DeviceProfile:d
             WHERE d == to_vertex(dp, "DeviceProfile");
  cards = SELECT c FROM dev_txns:t -(MADE_BY:e)-> Card:c
          LIMIT limit_n;
  PRINT cards AS result;
}
"""
    res = conn.gsql(f"USE GRAPH fraud_investigation\n{q}")
    print("Creation result:")
    print(res)

if __name__ == "__main__":
    main()
