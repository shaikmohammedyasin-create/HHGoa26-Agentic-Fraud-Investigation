import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pyTigerGraph as tg
import json

conn = tg.TigerGraphConnection(
    host=os.environ['TG_HOST'],
    graphname=os.environ['TG_GRAPH'],
    gsqlSecret=os.environ['TG_SECRET'],
    tgCloud=True
)
conn.getToken(os.environ['TG_SECRET'])

q = """USE GRAPH fraud_investigation
DROP QUERY cases_by_pattern
CREATE QUERY cases_by_pattern(STRING pattern, INT limit_n = 15) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc
    WHERE cc.pattern == pattern
    ORDER BY cc.closed_at DESC
    LIMIT limit_n;
  PRINT cases;
}
INSTALL QUERY cases_by_pattern
"""
print("Running GSQL...")
print(conn.gsql(q))

print("Invoking query via REST endpoint on empty graph...")
res = conn.runInstalledQuery("cases_by_pattern", {"pattern": "card_testing", "limit_n": 5})
print("Result:", json.dumps(res, indent=2))
