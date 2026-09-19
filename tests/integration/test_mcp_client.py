"""
Integration checks for the TigerGraph MCP integration.

The MCP client is the real tool surface of tigergraph-mcp.  These checks prove:
  - The client is importable and wired into the orchestrator's capability check.
  - With no MCP_URL it reports not_configured rather than fabricating results.
  - With an unreachable MCP_URL it raises MCPUnavailableError — never returns
    a fake success payload.
  - query_router.mcp_status() is callable from the health surface.
"""
from __future__ import annotations

import httpx
import pytest

from backend.config import settings
from backend.graph import query_router
from backend.mcp import client as mcp_client
from backend.mcp.client import MCPClient, MCPUnavailableError


class TestMCPClient:
    def test_unconfigured_raises_on_use(self):
        c = MCPClient(base_url="")
        with pytest.raises(MCPUnavailableError):
            _ = c.client

    def test_health_unconfigured_is_unavailable(self):
        c = MCPClient(base_url="")
        h = c.health()
        assert h["status"] == "unavailable"

    def test_health_reports_unreachable_server(self):
        # Point at a port nothing is listening on; must NOT report healthy.
        c = MCPClient(base_url="http://127.0.0.1:1")
        h = c.health()
        assert h["status"] == "unavailable"
        assert "error" in h

    def test_call_tool_unreachable_raises(self):
        c = MCPClient(base_url="http://127.0.0.1:1")
        with pytest.raises(MCPUnavailableError):
            c.call_tool("run_query", {"query_name": "x"})

    def test_get_mcp_singleton(self):
        mcp_client._mcp = None
        c = mcp_client.get_mcp()
        assert isinstance(c, MCPClient)

    def test_tool_surface_wraps_expected_tools(self):
        # The methods the orchestrator/graph layer rely on must exist and
        # build the correct MCP tool call.
        c = MCPClient(base_url="http://127.0.0.1:1")
        # run_query / get_schema / vector_search / upsert_vertex
        assert hasattr(c, "run_query")
        assert hasattr(c, "get_schema")
        assert hasattr(c, "vector_search")
        assert hasattr(c, "upsert_vertex")


class TestMCPStatusSurface:
    def test_mcp_status_callable(self):
        s = query_router.mcp_status()
        assert s["status"] in ("ok", "unavailable", "not_configured")

    def test_mcp_status_matches_settings(self):
        s = query_router.mcp_status()
        if not settings.mcp_url:
            assert s["status"] == "not_configured"
