import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

# Ensure TG_GRAPHNAME is set for tigergraph_mcp
if not os.environ.get("TG_GRAPHNAME"):
    os.environ["TG_GRAPHNAME"] = os.environ.get("TG_GRAPH", "fraud_investigation")

from tigergraph_mcp.connection_manager import ConnectionManager
from tigergraph_mcp.tools.schema_tools import get_graph_schema
from tigergraph_mcp.tools.node_tools import get_node, get_node_edges
from tigergraph_mcp.tools.query_tools import run_installed_query


async def test_mcp():
    print("=" * 60)
    print("TESTING OFFICIAL TIGERGRAPH MCP TOOLS LIVE")
    print("=" * 60)

    # 1. Schema discovery
    print("\n1. MCP Tool: get_graph_schema")
    schema_res = await get_graph_schema(graph_name="fraud_investigation")
    print("  Schema result type:", type(schema_res))
    schema_str = str(schema_res)
    print("  Schema summary (first 250 chars):", schema_str[:250])

    # 2. Transaction lookup via get_node
    print("\n2. MCP Tool: get_node (Transaction 3514030)")
    node_res = await get_node(vertex_type="Transaction", vertex_id="3514030")
    print("  get_node result:", str(node_res)[:250])

    # 3. Card/customer relationship via get_node_edges
    print("\n3. MCP Tool: get_node_edges (Customer C12382 OWNS)")
    edges_res = await get_node_edges(vertex_type="Customer", vertex_id="C12382", edge_type="OWNS")
    print("  get_node_edges result:", str(edges_res)[:250])

    # 4. Historical case retrieval via run_installed_query
    print("\n4. MCP Tool: run_installed_query (cases_by_pattern)")
    cases_res = await run_installed_query(
        query_name="cases_by_pattern",
        params={"pattern": "card_not_present_fraud", "limit_n": 2}
    )
    print("  run_installed_query result:", str(cases_res)[:250])

    await ConnectionManager.close_all()
    print("\n" + "=" * 60)
    print("ALL LIVE MCP TOOL CALLS SUCCEEDED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_mcp())
