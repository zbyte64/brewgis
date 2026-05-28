"""MCP Server — main server instance and stdio entrypoint."""

import logging

from mcp.server import FastMCP

from brewgis.workspace.mcp.tools import register_tools

logger = logging.getLogger(__name__)

server = FastMCP("brewgis-mcp")

register_tools(server)


def run_stdio() -> None:
    """Run the MCP server over stdio transport."""

    server.run(transport="stdio")
