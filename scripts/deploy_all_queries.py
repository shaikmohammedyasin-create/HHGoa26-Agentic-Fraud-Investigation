"""
Deploy and compile all HHGoa GSQL queries to TigerGraph Savanna Cloud.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pyTigerGraph as tg


# Standard GSQL query definitions tested for TigerGraph 4.x
QUERIES = {
    "card_transaction_history": """
CREATE QUERY card_transaction_history(VERTEX<Card> card, INT limit_n = 30) FOR GRAPH fraud_investigation {
  Start = {card};
  result = SELECT t
    FROM Start:c -(MADE:e)-> Transaction:t
    ORDER BY t.ts DESC
    LIMIT limit_n;
  PRINT result;
}
""",
    "card_window": """
CREATE QUERY card_window(VERTEX<Card> card, DATETIME center_ts, INT hours = 48) FOR GRAPH fraud_investigation {
  DATETIME lo = datetime_sub(center_ts, INTERVAL hours HOUR);
  DATETIME hi = datetime_add(center_ts, INTERVAL hours HOUR);
  Start = {card};
  result = SELECT t
    FROM Start:c -(MADE:e)-> Transaction:t
    WHERE t.ts >= lo AND t.ts <= hi
    ORDER BY t.ts;
  PRINT result;
}
""",
    "tiny_txn_sequence": """
CREATE QUERY tiny_txn_sequence(VERTEX<Card> card, DATETIME center_ts,
                               DOUBLE hours = 2.0, DOUBLE threshold = 10.0) FOR GRAPH fraud_investigation {
  DATETIME lo = datetime_sub(center_ts, INTERVAL hours HOUR);
  DATETIME hi = datetime_add(center_ts, INTERVAL hours HOUR);
  Start = {card};
  tiny = SELECT t
    FROM Start:c -(MADE:e)-> Transaction:t
    WHERE t.ts >= lo AND t.ts <= hi
      AND t.channel == "online"
      AND t.amount <= threshold
    ORDER BY t.ts;
  PRINT tiny;
}
""",
    "card_region_history": """
CREATE QUERY card_region_history(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  Start = {card};
  txns = SELECT t FROM Start:c -(MADE:e)-> Transaction:t;
  regions = SELECT r FROM txns:t -(BILLED_IN:e)-> BillingRegion:r;
  PRINT regions;
}
""",
    "card_email_history": """
CREATE QUERY card_email_history(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  Start = {card};
  txns = SELECT t FROM Start:c -(MADE:e)-> Transaction:t;
  emails = SELECT e FROM txns:t -(PURCHASER_EMAIL:e)-> EmailDomain:e;
  PRINT emails;
}
""",
    "card_product_history": """
CREATE QUERY card_product_history(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  Start = {card};
  prods = SELECT t FROM Start:c -(MADE:e)-> Transaction:t;
  PRINT prods[prods.product_cd];
}
""",
    "card_amount_stats": """
CREATE QUERY card_amount_stats(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  MinAccum<DOUBLE> @@min_amt;
  MaxAccum<DOUBLE> @@max_amt;
  SumAccum<DOUBLE> @@sum_amt;
  SumAccum<INT> @@n;

  Start = {card};
  all_ = SELECT t FROM Start:c -(MADE:e)-> Transaction:t
    POST-ACCUM @@min_amt += t.amount, @@max_amt += t.amount,
                @@sum_amt += t.amount, @@n += 1;

  PRINT @@min_amt AS min_amt, @@max_amt AS max_amt,
        (@@sum_amt / @@n) AS avg_amt, @@n AS n;
}
""",
    "card_velocity": """
CREATE QUERY card_velocity(VERTEX<Card> card, DATETIME center_ts, DOUBLE hours = 24.0) FOR GRAPH fraud_investigation {
  DATETIME lo = datetime_sub(center_ts, INTERVAL hours HOUR);
  DATETIME hi = datetime_add(center_ts, INTERVAL hours HOUR);
  SumAccum<DOUBLE> @@total_amt;
  SumAccum<INT> @@count;

  Start = {card};
  txns = SELECT t
    FROM Start:c -(MADE:e)-> Transaction:t
    WHERE t.ts >= lo AND t.ts <= hi
    ACCUM @@total_amt += t.amount, @@count += 1;

  PRINT @@total_amt AS total_amount, @@count AS n_transactions;
}
""",
    "customer_cards": """
CREATE QUERY customer_cards(VERTEX<Customer> cust) FOR GRAPH fraud_investigation {
  Start = {cust};
  cards = SELECT c FROM Start:cu -(OWNS:e)-> Card:c;
  PRINT cards;
}
""",
    "txn_by_id": """
CREATE QUERY txn_by_id(VERTEX<Transaction> txn_id) FOR GRAPH fraud_investigation {
  Seed = {txn_id};
  result = SELECT s FROM Seed:s;
  PRINT result;
}
""",
    "txn_identity": """
CREATE QUERY txn_identity(VERTEX<Transaction> txn_id) FOR GRAPH fraud_investigation {
  Seed = {txn_id};
  result = SELECT d
    FROM Seed:t -(FROM_DEVICE:e)-> DeviceProfile:d;
  PRINT result;
}
""",
    "txn_device_profile": """
CREATE QUERY txn_device_profile(VERTEX<Transaction> txn_id) FOR GRAPH fraud_investigation {
  Seed = {txn_id};
  result = SELECT d
    FROM Seed:t -(FROM_DEVICE:e)-> DeviceProfile:d;
  PRINT result[result.device_info, result.os, result.browser, result.screen];
}
""",
    "card_device_history": """
CREATE QUERY card_device_history(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  Start = {card};
  txns = SELECT t FROM Start:c -(MADE:e)-> Transaction:t;
  devices = SELECT d FROM txns:t -(FROM_DEVICE:e)-> DeviceProfile:d;
  PRINT devices;
}
""",
    "cases_involving_txn": """
CREATE QUERY cases_involving_txn(STRING txn_id) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc -(CC_INVOLVES:e)-> Transaction:t
    WHERE t.txn_id == txn_id;
  PRINT cases;
}
""",
    "cases_by_pattern": """
CREATE QUERY cases_by_pattern(STRING pattern, INT limit_n = 15) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc
    WHERE cc.pattern == pattern
    ORDER BY cc.closed_at DESC
    LIMIT limit_n;
  PRINT cases;
}
""",
    "search_case_notes": """
CREATE QUERY search_case_notes(STRING query, INT limit_n = 5) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc FROM AllCases:cc
    WHERE cc.analyst_notes LIKE ("%" + query + "%")
    ORDER BY cc.closed_at DESC
    LIMIT limit_n;
  PRINT cases;
}
""",
    "connected_card_cases": """
CREATE QUERY connected_card_cases(SET<STRING> card_ids) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc -(CC_CONNECTED_TO:e)-> Card:c
    WHERE card_ids.contains(c.card_id);
  PRINT cases;
}
""",
    "customer_closed_cases": """
CREATE QUERY customer_closed_cases(VERTEX<Customer> cust) FOR GRAPH fraud_investigation {
  Start = {cust};
  cards = SELECT c FROM Start:cu -(OWNS:e)-> Card:c;
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc -(CC_ON_CARD:e)-> Card:c
    WHERE c IN cards
    ORDER BY cc.opened_at DESC;
  PRINT cases;
}
""",
    "card_closed_cases": """
CREATE QUERY card_closed_cases(VERTEX<Card> card) FOR GRAPH fraud_investigation {
  AllCases = {ClosedCase.*};
  cases = SELECT cc
    FROM AllCases:cc -(CC_ON_CARD:e)-> Card:c
    WHERE c == card
    ORDER BY cc.opened_at DESC;
  PRINT cases;
}
""",
    "investigation_cases_for_customer": """
CREATE QUERY investigation_cases_for_customer(VERTEX<Customer> cust, INT limit_n = 10) FOR GRAPH fraud_investigation {
  AllCases = {InvestigationCase.*};
  cases = SELECT ic
    FROM AllCases:ic -(IC_FOR_CUSTOMER:e)-> Customer:cu
    WHERE cu == cust
    ORDER BY ic.opened_at DESC
    LIMIT limit_n;
  PRINT cases;
}
""",
    "investigation_cases_by_device": """
CREATE QUERY investigation_cases_by_device(STRING device_label, INT limit_n = 10) FOR GRAPH fraud_investigation {
  AllCases = {InvestigationCase.*};
  cases = SELECT ic
    FROM AllCases:ic -(IC_ON_DEVICE:e)-> DeviceProfile:d
    WHERE d.device_info == device_label
    ORDER BY ic.opened_at DESC
    LIMIT limit_n;
  PRINT cases;
}
""",
    "investigation_cases_involving_txn": """
CREATE QUERY investigation_cases_involving_txn(STRING txn_id, INT limit_n = 10) FOR GRAPH fraud_investigation {
  AllCases = {InvestigationCase.*};
  cases = SELECT ic
    FROM AllCases:ic -(IC_INVOLVES:e)-> Transaction:t
    WHERE t.txn_id == txn_id
    ORDER BY ic.opened_at DESC
    LIMIT limit_n;
  PRINT cases;
}
"""
}

# Graph Algorithm Queries
ALGORITHMS = {
    "device_connected_components": """
CREATE QUERY device_connected_components(INT max_iter = 10) FOR GRAPH fraud_investigation {
  MinAccum<STRING> @cc_id;
  cards = {Card.*};
  cards = SELECT c FROM cards:c POST-ACCUM c.@cc_id = c.card_id;

  FOREACH i IN RANGE[1, max_iter] DO
    txns = SELECT t FROM cards:c -(MADE:e)-> Transaction:t;
    devs = SELECT d FROM txns:t -(FROM_DEVICE:e)-> DeviceProfile:d;
    // Connect back via transactions and cards
    txns2 = SELECT t2 FROM devs:d <-(FROM_DEVICE:e)- Transaction:t2;
    cards2 = SELECT c2 FROM txns2:t2 -(MADE_BY:e)-> Card:c2
      ACCUM c2.@cc_id += c2.@cc_id;
  END;

  GroupByAccum<STRING cc_id, SetAccum<STRING> members> @@components;
  cards = SELECT c FROM cards:c POST-ACCUM @@components += (c.@cc_id -> c.card_id);
  PRINT @@components;
}
"""
}


def get_conn():
    host = os.environ["TG_HOST"].strip()
    raw_host = host
    if raw_host.startswith("https://"):
        raw_host = raw_host[8:]
    elif raw_host.startswith("http://"):
        raw_host = raw_host[7:]
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


def deploy_all():
    conn = get_conn()
    print("=" * 60)
    print("DEPLOYING GSQL QUERIES TO fraud_investigation")
    print("=" * 60)

    results = {}

    for qname, qdef in QUERIES.items():
        print(f"Creating query: {qname} ...", end=" ", flush=True)
        gsql_cmd = f"USE GRAPH fraud_investigation\n{qdef}"
        out = conn.gsql(gsql_cmd)
        if "Successfully created" in out or "Successfully dropped" in out:
            print("OK")
            results[qname] = "CREATED"
        else:
            print(f"FAILED: {out.strip()}")
            results[qname] = f"FAILED: {out.strip()}"

    print("-" * 60)
    print(f"Total queries defined: {len(results)}")
    created = [k for k, v in results.items() if v == "CREATED"]
    print(f"Successfully created: {len(created)} / {len(QUERIES)}")

    if created:
        print("\nInstalling all created queries (this may take 1-2 minutes)...")
        install_cmd = f"USE GRAPH fraud_investigation\nINSTALL QUERY {', '.join(created)}"
        out = conn.gsql(install_cmd)
        print("Install Output:")
        print(out)

    return results


if __name__ == "__main__":
    deploy_all()
