"""
TigerGraph Savanna Cloud Connection Test Script.

Tests:
1. Environment configuration validation (TG_HOST, TG_GRAPH, TG_SECRET / TG_TOKEN)
2. DNS resolution for TG_HOST
3. pyTigerGraph connection & authentication to TigerGraph Savanna Cloud
4. Verification of target graph (fraud_investigation)
5. Schema retrieval (vertices & edges)
6. One harmless read-only query (vertex count / metadata)

CRITICAL SECURITY CONSTRAINT:
- Never print, log, or expose TG_SECRET or TG_TOKEN in any output.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# Add project root to sys.path so backend imports work
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env explicitly if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

import pyTigerGraph as tg


def mask_secret(val: str) -> str:
    """Safely mask secret/token for logging without exposing it."""
    if not val:
        return "<not set>"
    if len(val) <= 6:
        return "***"
    return f"{val[:3]}...{val[-3:]} ({len(val)} chars)"


def run_connection_test() -> bool:
    print("=" * 65)
    print("  TIGERGRAPH SAVANNA CLOUD CONNECTION TEST")
    print("=" * 65)

    tg_host = os.environ.get("TG_HOST", "").strip()
    tg_graph = os.environ.get("TG_GRAPH", "fraud_investigation").strip()
    tg_secret = os.environ.get("TG_SECRET", "").strip()
    tg_token = os.environ.get("TG_TOKEN", "").strip()
    tg_port = os.environ.get("TG_PORT", "443").strip()
    tg_protocol = os.environ.get("TG_PROTOCOL", "https").strip()

    # 1. Environment Variable Validation
    print("\n[1/5] Checking environment configuration...")
    missing_vars = []
    if not tg_host:
        missing_vars.append("TG_HOST")
    if not tg_graph:
        missing_vars.append("TG_GRAPH")
    if not tg_secret and not tg_token:
        missing_vars.append("TG_SECRET")

    print(f"      TG_HOST:     {tg_host if tg_host else '<MISSING>'}")
    print(f"      TG_GRAPH:    {tg_graph if tg_graph else '<MISSING>'}")
    print(f"      TG_SECRET:   {'CONFIGURED [MASKED: ' + mask_secret(tg_secret) + ']' if tg_secret else '<NOT SET>'}")
    print(f"      TG_TOKEN:    {'CONFIGURED [MASKED: ' + mask_secret(tg_token) + ']' if tg_token else '<NOT SET>'}")
    print(f"      TG_PORT:     {tg_port}")
    print(f"      TG_PROTOCOL: {tg_protocol}")

    if missing_vars:
        print("\n" + "!" * 65)
        print("  FAILURE: Missing required environment variable(s):")
        for mv in missing_vars:
            print(f"    - {mv}")
        print("\n  Please define these in your environment or in .env:")
        if "TG_HOST" in missing_vars:
            print("    TG_HOST=<your-savanna-subdomain>.i.tgcloud.io")
        if "TG_SECRET" in missing_vars:
            print("    TG_SECRET=<your-tigergraph-secret>")
        if "TG_GRAPH" in missing_vars:
            print("    TG_GRAPH=fraud_investigation")
        print("!" * 65)
        return False

    print("      Configuration check: OK")

    # 2. Hostname validation & DNS resolution
    print(f"\n[2/5] Testing DNS resolution for TG_HOST...")
    raw_host = tg_host
    if raw_host.startswith("https://"):
        raw_host = raw_host[8:]
    elif raw_host.startswith("http://"):
        raw_host = raw_host[7:]
    raw_host = raw_host.split(":")[0].split("/")[0]

    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(raw_host)
        print(f"      SUCCESS: Resolved '{raw_host}' -> {resolved_ip}")
    except socket.gaierror as exc:
        print(f"      FAILED: Cannot resolve hostname '{raw_host}': {exc}")
        # Help user if they supplied just the workspace ID without domain
        candidate = f"{raw_host}.i.tgcloud.io"
        try:
            candidate_ip = socket.gethostbyname(candidate)
            print(f"\n      TIP: Found valid Savanna domain '{candidate}' -> {candidate_ip}")
            print(f"      Update TG_HOST={candidate} in your .env file.")
        except socket.gaierror:
            pass
        print("\n" + "!" * 65)
        print("  FAILURE: DNS resolution failed.")
        print("  Please verify your TG_HOST FQDN from TigerGraph Savanna.")
        print("!" * 65)
        return False

    # 3. pyTigerGraph Connection Initialization & Authentication
    print(f"\n[3/5] Connecting to TigerGraph Savanna at {tg_protocol}://{raw_host}:{tg_port}...")
    full_host_url = f"{tg_protocol}://{raw_host}"
    is_cloud = True

    try:
        conn = tg.TigerGraphConnection(
            host=full_host_url,
            graphname=tg_graph,
            gsqlSecret=tg_secret if tg_secret else "",
            apiToken=tg_token if tg_token else "",
            tgCloud=is_cloud,
            sslPort=tg_port,
        )

        # Authenticate using secret if provided
        if tg_secret and not conn.apiToken:
            print("      Authenticating using TG_SECRET to request token...")
            token = conn.getToken(tg_secret, setToken=True)
            if isinstance(token, tuple):
                conn.apiToken = token[0]
            elif isinstance(token, str):
                conn.apiToken = token
            print("      Authentication SUCCESS: Token acquired.")
        elif conn.apiToken:
            print("      Using provided TG_TOKEN for authentication.")
        else:
            print("      No secret or token available.")
            return False

    except Exception as exc:
        print("\n" + "!" * 65)
        print(f"  FAILURE: TigerGraph authentication / connection error: {exc}")
        print("!" * 65)
        return False

    # 4. Target Graph Verification & Schema Information
    print(f"\n[4/5] Verifying target graph '{tg_graph}' and retrieving schema...")
    try:
        # Check target graph matches
        print(f"      Active graph targeted: {conn.graphname}")
        if conn.graphname != tg_graph:
            print(f"      FAILURE: Connected graph '{conn.graphname}' does not match expected '{tg_graph}'")
            return False

        vertex_types = conn.getVertexTypes()
        edge_types = conn.getEdgeTypes()

        print(f"      SUCCESS: Retrieved graph schema for '{conn.graphname}':")
        print(f"        Vertices ({len(vertex_types)}): {', '.join(vertex_types)}")
        print(f"        Edges ({len(edge_types)}):    {', '.join(edge_types)}")

        # Safety check: ensure Transaction_Fraud was not touched
        if "Transaction_Fraud" in conn.graphname:
            print("      WARNING: Connected to Transaction_Fraud instead of fraud_investigation!")
            return False

    except Exception as exc:
        print("\n" + "!" * 65)
        print(f"  FAILURE: Could not retrieve graph/schema information: {exc}")
        print("!" * 65)
        return False

    # 5. Harmless Read-Only Query
    print(f"\n[5/5] Executing harmless read-only query on '{tg_graph}'...")
    try:
        # Read-only query: count vertices across the graph
        counts = conn.getVertexCount("*")
        print(f"      SUCCESS: Read-only query executed.")
        print(f"      Vertex counts in '{tg_graph}': {counts}")

    except Exception as exc:
        print(f"      Harmless query warning: {exc}")
        # Try fallback read-only check
        try:
            echo_res = conn.echo()
            print(f"      Echo check response: {echo_res}")
        except Exception as e2:
            print("\n" + "!" * 65)
            print(f"  FAILURE: Read-only query failed: {e2}")
            print("!" * 65)
            return False

    print("\n" + "=" * 65)
    print("  RESULT: SUCCESS")
    print(f"  TigerGraph Savanna Cloud connected to graph: '{conn.graphname}'")
    print("=" * 65)
    return True


if __name__ == "__main__":
    success = run_connection_test()
    sys.exit(0 if success else 1)
