import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.graph.tg_adapter import get_connection
import json

def main():
    conn = get_connection()
    schema = conn.getSchema()
    print("Graph Name:", conn.graphname)
    print("\nEdge types in live schema:")
    for e in schema.get("EdgeTypes", []):
        name = e.get("Name")
        src = e.get("FromVertexTypeName")
        dst = e.get("ToVertexTypeName")
        directed = e.get("IsDirected")
        config = e.get("Config", {})
        print(f"  {name}: {src} -> {dst} (IsDirected={directed}, Config={config})")

    print("\nInstalled queries on live graph:")
    installed = conn.getInstalledQueries()
    print(json.dumps(installed, indent=2))

if __name__ == "__main__":
    main()
