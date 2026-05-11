"""Tool registration aggregator — imports and registers all tool modules."""

from __future__ import annotations

import logging

from brewgis.workspace.mcp.tools import workspace as workspace_tools
from brewgis.workspace.mcp.tools import scenario as scenario_tools
from brewgis.workspace.mcp.tools import layer as layer_tools
from brewgis.workspace.mcp.tools import paint as paint_tools
from brewgis.workspace.mcp.tools import analysis as analysis_tools
from brewgis.workspace.mcp.tools import data_import as data_import_tools
from brewgis.workspace.mcp.tools import reports as reports_tools

logger = logging.getLogger(__name__)


def register_tools(server: object) -> None:
    """Register all tool modules with the MCP server."""
    workspace_tools.register_tools(server)
    scenario_tools.register_tools(server)
    layer_tools.register_tools(server)
    paint_tools.register_tools(server)
    analysis_tools.register_tools(server)
    data_import_tools.register_tools(server)
    reports_tools.register_tools(server)
    logger.info("All MCP tool modules registered")
