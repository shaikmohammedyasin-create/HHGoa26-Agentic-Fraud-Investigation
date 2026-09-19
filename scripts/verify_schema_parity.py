"""
Schema Parity Verifier: Live TigerGraph vs. Local schema.gsql
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import pyTigerGraph as tg


def get_live_schema():
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
    return conn, conn.getSchema()


def run_parity_check():
    conn, live = get_live_schema()

    # Local schema expectations based on tigergraph/schema/schema.gsql
    expected_vertices = {
        "Customer": {
            "primary_id": "customer_id",
            "attributes": {"first_seen": "DATETIME", "last_seen": "DATETIME"}
        },
        "Card": {
            "primary_id": "card_id",
            "attributes": {"customer_id": "STRING", "card4": "STRING", "card6": "STRING"}
        },
        "Transaction": {
            "primary_id": "txn_id",
            "attributes": {
                "ts": "DATETIME",
                "amount": "DOUBLE",
                "product_cd": "STRING",
                "channel": "STRING",
                "addr1": "STRING",
                "addr2": "STRING",
                "risk_score": "DOUBLE",
                "p_email": "STRING",
                "r_email": "STRING",
                "customer_id": "STRING",
                "card_id": "STRING"
            }
        },
        "DeviceProfile": {
            "primary_id": "device_profile_id",
            "attributes": {
                "device_info": "STRING",
                "os": "STRING",
                "browser": "STRING",
                "screen": "STRING",
                "device_type": "STRING"
            }
        },
        "EmailDomain": {
            "primary_id": "domain",
            "attributes": {}
        },
        "BillingRegion": {
            "primary_id": "region_code",
            "attributes": {"country_code": "STRING"}
        },
        "ClosedCase": {
            "primary_id": "case_id",
            "attributes": {
                "customer_id": "STRING",
                "card_id": "STRING",
                "opened_at": "DATETIME",
                "closed_at": "DATETIME",
                "outcome": "STRING",
                "pattern": "STRING",
                "exposure_usd": "DOUBLE",
                "n_txns": "INT",
                "report_filed": "BOOL",
                "analyst_notes": "STRING"
            }
        },
        "InvestigationCase": {
            "primary_id": "case_id",
            "attributes": {
                "trigger_type": "STRING",
                "trigger_text": "STRING",
                "opened_at": "DATETIME",
                "status": "STRING",
                "verdict": "STRING",
                "fraud_probability": "DOUBLE",
                "pattern": "STRING",
                "exposure_usd": "DOUBLE",
                "summary": "STRING"
            }
        }
    }

    expected_edges = {
        "OWNS": {"from": "Customer", "to": "Card", "directed": True, "reverse": None},
        "MADE": {"from": "Card", "to": "Transaction", "directed": True, "reverse": "MADE_BY"},
        "FROM_DEVICE": {"from": "Transaction", "to": "DeviceProfile", "directed": True, "reverse": None},
        "PURCHASER_EMAIL": {"from": "Transaction", "to": "EmailDomain", "directed": True, "reverse": None},
        "RECIPIENT_EMAIL": {"from": "Transaction", "to": "EmailDomain", "directed": True, "reverse": None},
        "BILLED_IN": {"from": "Transaction", "to": "BillingRegion", "directed": True, "reverse": None},
        "NEXT_TXN": {"from": "Transaction", "to": "Transaction", "directed": True, "reverse": None},
        "CC_INVOLVES": {"from": "ClosedCase", "to": "Transaction", "directed": True, "reverse": None},
        "CC_ON_CARD": {"from": "ClosedCase", "to": "Card", "directed": True, "reverse": None},
        "CC_CONNECTED_TO": {"from": "ClosedCase", "to": "Card", "directed": True, "reverse": None},
        "IC_INVOLVES": {"from": "InvestigationCase", "to": "Transaction", "directed": True, "reverse": None},
        "IC_ON_CARD": {"from": "InvestigationCase", "to": "Card", "directed": True, "reverse": None},
        "IC_FOR_CUSTOMER": {"from": "InvestigationCase", "to": "Customer", "directed": True, "reverse": None},
        "IC_ON_DEVICE": {"from": "InvestigationCase", "to": "DeviceProfile", "directed": True, "reverse": None},
    }

    live_v_map = {v["Name"]: v for v in live.get("VertexTypes", [])}
    live_e_map = {e["Name"]: e for e in live.get("EdgeTypes", [])}

    report = {
        "graph": conn.graphname,
        "vertices": {},
        "edges": {},
        "all_matched": True
    }

    # Verify vertices
    for vname, vexpect in expected_vertices.items():
        if vname not in live_v_map:
            report["vertices"][vname] = {"status": "MISMATCH", "reason": "Missing vertex"}
            report["all_matched"] = False
            continue

        lv = live_v_map[vname]
        pid_name = lv.get("PrimaryId", {}).get("AttributeName")
        if pid_name != vexpect["primary_id"]:
            report["vertices"][vname] = {
                "status": "MISMATCH",
                "reason": f"PrimaryId mismatch: expected {vexpect['primary_id']}, got {pid_name}"
            }
            report["all_matched"] = False
            continue

        l_attrs = {a["AttributeName"]: a["AttributeType"]["Name"] for a in lv.get("Attributes", [])}
        missing_attrs = []
        mismatched_types = []
        for exp_k, exp_type in vexpect["attributes"].items():
            if exp_k not in l_attrs:
                missing_attrs.append(exp_k)
            elif l_attrs[exp_k].upper() != exp_type.upper():
                mismatched_types.append(f"{exp_k} (expected {exp_type}, got {l_attrs[exp_k]})")

        if missing_attrs or mismatched_types:
            report["vertices"][vname] = {
                "status": "MISMATCH",
                "missing_attrs": missing_attrs,
                "mismatched_types": mismatched_types
            }
            report["all_matched"] = False
        else:
            report["vertices"][vname] = {
                "status": "MATCH",
                "primary_id": pid_name,
                "attributes_count": len(l_attrs)
            }

    # Verify edges
    for ename, eexpect in expected_edges.items():
        if ename not in live_e_map:
            report["edges"][ename] = {"status": "MISMATCH", "reason": "Missing edge"}
            report["all_matched"] = False
            continue

        le = live_e_map[ename]
        l_from = le.get("FromVertexTypeName")
        l_to = le.get("ToVertexTypeName")
        l_dir = le.get("IsDirected")
        l_rev = le.get("Config", {}).get("REVERSE_EDGE")

        mismatches = []
        if l_from != eexpect["from"]:
            mismatches.append(f"From mismatch: expected {eexpect['from']}, got {l_from}")
        if l_to != eexpect["to"]:
            mismatches.append(f"To mismatch: expected {eexpect['to']}, got {l_to}")
        if l_dir != eexpect["directed"]:
            mismatches.append(f"Directed mismatch: expected {eexpect['directed']}, got {l_dir}")
        if eexpect["reverse"] and l_rev != eexpect["reverse"]:
            mismatches.append(f"Reverse mismatch: expected {eexpect['reverse']}, got {l_rev}")

        if mismatches:
            report["edges"][ename] = {"status": "MISMATCH", "reasons": mismatches}
            report["all_matched"] = False
        else:
            report["edges"][ename] = {
                "status": "MATCH",
                "from": l_from,
                "to": l_to,
                "directed": l_dir,
                "reverse_edge": l_rev
            }

    print(json.dumps(report, indent=2))
    return report["all_matched"], report


if __name__ == "__main__":
    ok, _ = run_parity_check()
    sys.exit(0 if ok else 1)
