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


def run_sse(host: str = "0.0.0.0", port: int = 8002) -> None:
    """Run the MCP server over SSE transport (long-lived HTTP).

    FastMCP serves the SSE endpoint at ``http://<host>:<port>/sse``.
    The host and port are configured via ``server.settings``.
    The server is ready to accept connections immediately.
    """

    server.settings.host = host
    server.settings.port = port
    server.run(transport="sse")


def run_streamable_http(host: str = "0.0.0.0", port: int = 8002) -> None:
    """Run the MCP server over Streamable HTTP transport.

    FastMCP serves the endpoint at ``http://<host>:<port>/mcp``.
    This is the modern MCP transport preferred by OMP.
    """

    server.settings.host = host
    server.settings.port = port
    server.run(transport="streamable-http")
