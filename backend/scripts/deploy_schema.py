"""
Deploy schema into TigerGraph Savanna 'fraud_investigation' graph.

1. Connects to TigerGraph using settings in .env
2. Executes tigergraph/schema/deploy_schema_change.gsql
3. Queries TigerGraph REST API to verify deployed vertex and edge types

Usage:
    python -m backend.scripts.deploy_schema
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings
from backend.graph.tg_adapter import _tg_base_url


def deploy_and_verify():
    print("=" * 65)
    print("TIGERGRAPH SCHEMA DEPLOYMENT: fraud_investigation")
    print("=" * 65)
    print(f"Target Graph:    {settings.tg_graph}")
    print(f"Target Host:     {settings.tg_host}")
    print(f"Target Port:     {settings.tg_port}")
    print(f"Token present:   {bool(settings.tg_token)}")
    print("-" * 65)

    if not settings.tg_token:
        print("ERROR: TG_TOKEN is empty in .env.")
        print("Please enter your TigerGraph token in .env before running.")
        return False

    base_url = _tg_base_url()
    headers = {"Authorization": f"Bearer {settings.tg_token}"}

    # Step 1: Check live connection
    print("\n[Step 1/3] Checking connection to TigerGraph...")
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{base_url}/echo")
            print(f"  /echo status: HTTP {r.status_code}")
    except Exception as exc:
        print(f"  ERROR: Unable to connect to TigerGraph at {base_url}: {exc}")
        return False

    # Step 2: Read schema change GSQL
    schema_file = Path(__file__).resolve().parents[2] / "tigergraph" / "schema" / "deploy_hhgoa_schema.gsql"
    if not schema_file.exists():
        print(f"  ERROR: {schema_file} not found.")
        return False
    gsql_code = schema_file.read_text(encoding="utf-8")
    print(f"\n[Step 2/3] Executing schema change job on graph '{settings.tg_graph}'...")

    # Post GSQL query to TigerGraph GSQL server
    # TigerGraph supports POST /gsqlserver/gsql/query or /gsql
    deployed = False
    for endpoint in [f"{base_url}/gsqlserver/gsql/query", f"{base_url}/gsql"]:
        try:
            with httpx.Client(timeout=120) as client:
                r = client.post(endpoint, content=gsql_code, headers={**headers, "Content-Type": "text/plain"})
                if r.status_code == 200:
                    data = r.json()
                    print(f"  Deployment response from {endpoint}:")
                    print(f"  {data}")
                    deployed = True
                    break
        except Exception as exc:
            print(f"  Tried {endpoint}: {exc}")

    if not deployed:
        print("\n  Automatic REST GSQL runner could not complete directly.")
        print("  You can execute tigergraph/schema/deploy_schema_change.gsql")
        print("  directly in TigerGraph Savanna's GSQL Web Editor.")

    # Step 3: Verify deployed schema via REST API
    print(f"\n[Step 3/3] Querying live TigerGraph graph metadata for '{settings.tg_graph}'...")
    try:
        with httpx.Client(timeout=15) as client:
            # Query graph schema endpoint
            r = client.get(f"{base_url}/graphs/{settings.tg_graph}", headers=headers)
            if r.status_code == 200:
                meta = r.json()
                results = meta.get("results", {}) if isinstance(meta, dict) else {}
                vertices = [v.get("Name") or v.get("name") or str(v) for v in results.get("Vertices", [])]
                edges = [e.get("Name") or e.get("name") or str(e) for e in results.get("Edges", [])]
                print(f"  SUCCESS! Live TigerGraph schema for '{settings.tg_graph}':")
                print(f"  Actual Vertices ({len(vertices)}): {vertices}")
                print(f"  Actual Edges ({len(edges)}): {edges}")
                print("=" * 65)
                return True
            else:
                print(f"  Live metadata returned HTTP {r.status_code}: {r.text[:200]}")
    except Exception as exc:
        print(f"  Failed to query live graph schema: {exc}")

    print("=" * 65)
    return False


if __name__ == "__main__":
    deploy_and_verify()
