"""Tests for SQLMesh MCP tool module."""

from __future__ import annotations

from unittest.mock import MagicMock

from brewgis.workspace.mcp.tools.sqlmesh import _audit_names
from brewgis.workspace.mcp.tools.sqlmesh import _columns_to_list
from brewgis.workspace.mcp.tools.sqlmesh import _depends_on_list
from brewgis.workspace.mcp.tools.sqlmesh import _get_cached_context
from brewgis.workspace.mcp.tools.sqlmesh import _grain_names
from brewgis.workspace.mcp.tools.sqlmesh import _model_kind_name
from brewgis.workspace.mcp.tools.sqlmesh import _model_source_type
from brewgis.workspace.mcp.tools.sqlmesh import register_tools


class TestSqlmeshToolRegistration:
    """Test that the sqlmesh MCP tool module registers correctly."""

    def test_register_tools_is_callable(self) -> None:
        """register_tools function is exported and callable."""
        assert callable(register_tools)

    def test_all_tools_are_registered(self) -> None:
        """All 10 expected tools are registered via the server."""
        mock_server = MagicMock()
        registered: list[dict] = []

        def capture_tool(**kw: object) -> object:
            registered.append(kw)
            return lambda f: f

        mock_server.tool = capture_tool
        register_tools(mock_server)

        assert len(registered) == 10

    def test_register_tools_integration(self) -> None:
        """Registering sqlmesh tools works via the aggregator pattern."""
        calls: list[object] = []

        def capture_decorator(**kw: object) -> object:
            calls.append(kw)
            return lambda f: f

        mock_server = MagicMock()
        mock_server.tool = capture_decorator
        register_tools(mock_server)

        assert len(calls) == 10

    def test_cached_context_importable(self) -> None:
        """The cached context helper can be imported."""
        assert callable(_get_cached_context)

    def test_model_kind_name_none(self) -> None:
        """_model_kind_name returns UNKNOWN for None kind."""

        class FakeModel:
            kind = None

        assert _model_kind_name(FakeModel()) == "UNKNOWN"

    def test_model_kind_name_missing(self) -> None:
        """_model_kind_name returns UNKNOWN for missing kind."""

        class BareModel:
            pass

        assert _model_kind_name(BareModel()) == "UNKNOWN"

    def test_model_source_type_sql(self) -> None:
        """_model_source_type returns sql for SqlModel-like objects."""

        class SqlModel:
            pass

        assert _model_source_type(SqlModel()) == "sql"

    def test_model_source_type_python(self) -> None:
        """_model_source_type returns python for PythonModel-like objects."""

        class PythonModel:
            pass

        assert _model_source_type(PythonModel()) == "python"

    def test_model_source_type_seed(self) -> None:
        """_model_source_type returns seed for SeedModel-like objects."""

        class SeedModel:
            pass

        assert _model_source_type(SeedModel()) == "seed"

    def test_model_source_type_external(self) -> None:
        """_model_source_type returns external for ExternalModel-like objects."""

        class ExternalModel:
            pass

        assert _model_source_type(ExternalModel()) == "external"

    def test_columns_to_list_none(self) -> None:
        """_columns_to_list returns [] for object with no columns."""
        assert _columns_to_list(object()) == []

    def test_audit_names_none(self) -> None:
        """_audit_names returns [] for object with no audits."""
        assert _audit_names(object()) == []

    def test_grain_names_none(self) -> None:
        """_grain_names returns [] for object with no grains."""
        assert _grain_names(object()) == []

    def test_depends_on_list_none(self) -> None:
        """_depends_on_list returns [] for object with no depends_on."""
        assert _depends_on_list(object()) == []
