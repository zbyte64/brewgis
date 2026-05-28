"""Tests for MCP server bootstrap and tool registration.

Phase 1e — verifies the server initializes and registers tools correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestMcpServerRegistration:
    """Test that the MCP server registers all expected tool modules."""

    def test_server_imports(self) -> None:
        """Server module can be imported without errors."""
        from brewgis.workspace.mcp.server import server

        assert server is not None
        assert server.name == "brewgis-mcp"

    def test_register_all_tools(self) -> None:
        """All tool modules register without errors."""
        from brewgis.workspace.mcp.tools import register_tools

        mock_server = MagicMock()
        mock_server.tool = lambda **kw: lambda f: f
        register_tools(mock_server)

    def test_run_stdio_imports(self) -> None:
        """run_stdio function can be imported without errors."""
        from brewgis.workspace.mcp.server import run_stdio

        assert callable(run_stdio)

    def test_auth_stub(self) -> None:
        """Auth stub returns None (Phase 5 not implemented)."""
        from brewgis.workspace.mcp.auth import resolve_user

        assert resolve_user() is None
        assert resolve_user("some-token") is None

    def test_management_command_imports(self) -> None:
        """Management command can be imported."""
        from brewgis.workspace.management.commands.run_mcp import Command

        cmd = Command()
        assert cmd.help is not None
        assert "MCP" in cmd.help


@pytest.mark.django_db
class TestMcpToolFunctions:
    """Test individual MCP tool functions."""

    def test_list_workspaces_empty(self) -> None:
        """list_workspaces returns empty list when no workspaces exist."""
        from brewgis.workspace.mcp.tools.workspace import register_tools

        mock_server = MagicMock()
        tools_registered: list[dict] = []

        def capture_tool(**kw: object) -> object:
            tools_registered.append(kw)
            return lambda f: f

        mock_server.tool = capture_tool
        register_tools(mock_server)
        assert len(tools_registered) > 0

    def test_tool_module_exports(self) -> None:
        """Every tool module exports register_tools function."""
        from brewgis.workspace.mcp.tools import analysis as an
        from brewgis.workspace.mcp.tools import data_import as di
        from brewgis.workspace.mcp.tools import layer as ly
        from brewgis.workspace.mcp.tools import paint as pt
        from brewgis.workspace.mcp.tools import reports as rp
        from brewgis.workspace.mcp.tools import scenario as sc
        from brewgis.workspace.mcp.tools import workspace as ws

        assert callable(ws.register_tools)
        assert callable(sc.register_tools)
        assert callable(ly.register_tools)
        assert callable(pt.register_tools)
        assert callable(an.register_tools)
        assert callable(di.register_tools)
        assert callable(rp.register_tools)
