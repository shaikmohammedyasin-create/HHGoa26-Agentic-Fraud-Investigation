"""
TigerGraph MCP client.

Wraps the official tigergraph-mcp tool surface:
  https://github.com/tigergraph/tigergraph-mcp

When MCP_URL is set, tools call the MCP server.
When MCP is unavailable, returns structured errors — never fakes results.
"""
from __future__ import annotations

from typing import Any

import httpx

from backend.config import settings
from backend.logging import get_logger

log = get_logger(__name__)


class MCPUnavailableError(Exception):
    pass


class MCPClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.mcp_url).rstrip("/")
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            if not self.base_url:
                raise MCPUnavailableError("MCP_URL is not configured")
            self._client = httpx.Client(base_url=self.base_url, timeout=30)
        return self._client

    def health(self) -> dict[str, str]:
        try:
            r = self.client.get("/health")
            r.raise_for_status()
            return {"status": "healthy"}
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Call an MCP-exposed TigerGraph tool.

        Expected tools (from tigergraph-mcp):
          - get_schema: Discover graph schema
          - run_query: Execute an installed GSQL query
          - run_gsql: Execute raw GSQL
          - get_vertices: Get vertices by type
          - get_edges: Get edges
          - upsert_data: Upsert vertices/edges
          - vector_search: Search vector store
        """
        try:
            r = self.client.post(
                "/tools/call",
                json={"name": tool_name, "arguments": params},
            )
            r.raise_for_status()
            return r.json()
        except httpx.ConnectError:
            raise MCPUnavailableError(f"MCP server at {self.base_url} is not reachable")
        except Exception as exc:
            log.warning("mcp.tool.error", tool=tool_name, error=str(exc))
            raise MCPUnavailableError(str(exc))

    def run_query(self, query_name: str, params: dict[str, Any] | None = None) -> Any:
        return self.call_tool("run_query", {
            "query_name": query_name,
            "params": params or {},
        })

    def get_schema(self) -> Any:
        return self.call_tool("get_schema", {})

    def vector_search(self, query_text: str, top_k: int = 5) -> Any:
        return self.call_tool("vector_search", {
            "query": query_text,
            "top_k": top_k,
        })

    def upsert_vertex(self, vertex_type: str, vertex_id: str, attrs: dict) -> Any:
        return self.call_tool("upsert_data", {
            "vertex_type": vertex_type,
            "vertex_id": vertex_id,
            "attributes": attrs,
        })

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None


_mcp: MCPClient | None = None


def get_mcp() -> MCPClient:
    global _mcp
    if _mcp is None:
        _mcp = MCPClient()
    return _mcp
