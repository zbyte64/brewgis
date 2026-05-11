"""MCP Server — main server instance and stdio entrypoint."""

from __future__ import annotations

import logging

import mcp.server as mcp_server

from brewgis.workspace.mcp.tools import register_tools

logger = logging.getLogger(__name__)

server = mcp_server.Server("brewgis-mcp")

register_tools(server)


def run_stdio() -> None:
    """Run the MCP server over stdio transport."""
    from mcp import run

    run(transport="stdio")
