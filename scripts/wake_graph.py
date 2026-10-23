"""
Wake-up checker for the cloud TigerGraph instance (live mode helper).

Tigerscale cloud graphs idle-suspend; the first requests after hours of
silence may find the engine down. This script polls /health every few
seconds until the graph reports healthy (or a timeout), so a demo can be
pre-warmed before judges arrive.

Usage:  python scripts/wake_graph.py [WEB_URL] [--timeout-seconds 600]
Exit:   0 graph healthy, 1 timed out or unreachable.
"""
from __future__ import annotations

import sys
import time

import httpx

DEFAULT_TIMEOUT_SECONDS = 600
POLL_SECONDS = 5.0


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "http://127.0.0.1:8008"
    deadline = time.time() + DEFAULT_TIMEOUT_SECONDS

    print(f"Polling {base}/health every {int(POLL_SECONDS)} s "
          f"(timeout {DEFAULT_TIMEOUT_SECONDS} s)")
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base}/health", timeout=10.0)
            data = resp.json()
        except Exception as exc:
            print(f"  app not reachable yet ({exc.__class__.__name__})")
            time.sleep(POLL_SECONDS)
            continue

        graph = data.get("graph") or {}
        state = graph.get("tigergraph") or graph.get("local") or graph.get("status")
        print(f"  app={data.get('status')} graph={state} "
              f"demo_mode={data.get('demo_mode')}")
        if state == "healthy":
            print("Graph is healthy - you are ready for the demo.")
            return 0
        time.sleep(POLL_SECONDS)

    print("Timed out waiting for a healthy graph.")
    print("Tip: run in demo mode (DEMO_MODE=1) which needs no graph instance.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
