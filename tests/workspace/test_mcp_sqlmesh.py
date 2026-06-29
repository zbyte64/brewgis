"""Tests for SQLMesh MCP tool module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from brewgis.workspace.mcp.tools.sqlmesh import ModelNotResolvedError
from brewgis.workspace.mcp.tools.sqlmesh import PlanStats
from brewgis.workspace.mcp.tools.sqlmesh import _audit_names
from brewgis.workspace.mcp.tools.sqlmesh import _columns_to_list
from brewgis.workspace.mcp.tools.sqlmesh import _context_cache
from brewgis.workspace.mcp.tools.sqlmesh import _depends_on_list
from brewgis.workspace.mcp.tools.sqlmesh import _extract_post_statement_indexes
from brewgis.workspace.mcp.tools.sqlmesh import _grain_names
from brewgis.workspace.mcp.tools.sqlmesh import _model_kind_name
from brewgis.workspace.mcp.tools.sqlmesh import _model_source_type
from brewgis.workspace.mcp.tools.sqlmesh import _resolve_model_name
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

        assert len(registered) == 12

    def test_register_tools_integration(self) -> None:
        """Registering sqlmesh tools works via the aggregator pattern."""
        calls: list[object] = []

        def capture_decorator(**kw: object) -> object:
            calls.append(kw)
            return lambda f: f

        mock_server = MagicMock()
        mock_server.tool = capture_decorator
        register_tools(mock_server)

        assert len(calls) == 12

    def test_cached_context_importable(self) -> None:
        """The context cache can be imported."""
        assert hasattr(_context_cache, "get")
        assert hasattr(_context_cache, "refresh")

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


class TestResolveModelName:
    """Tests for _resolve_model_name fuzzy resolution."""

    models: dict[str, object] = {
        "brewgis.assessor.parcel_dasymetric_weights": object(),
        "brewgis.assessor.parcel_du_estimation": object(),
        "brewgis.analysis.core_end_state": object(),
        "brewgis.analysis.core_increment": object(),
        "brewgis.staging.overture_land_use": object(),
        "brewgis.comparison.sacog_parcel_shim": object(),
    }

    def test_exact_fqn(self) -> None:
        """Exact FQN resolves correctly."""
        result = _resolve_model_name(
            "brewgis.assessor.parcel_dasymetric_weights", self.models
        )
        assert result == "brewgis.assessor.parcel_dasymetric_weights"

    def test_quoted_fqn(self) -> None:
        """SQL-quoted FQN resolves correctly."""
        result = _resolve_model_name(
            '"brewgis"."assessor"."parcel_dasymetric_weights"', self.models
        )
        assert result == "brewgis.assessor.parcel_dasymetric_weights"

    def test_short_name(self) -> None:
        """Bare model short name resolves correctly."""
        result = _resolve_model_name("parcel_dasymetric_weights", self.models)
        assert result == "brewgis.assessor.parcel_dasymetric_weights"

    def test_two_part_name(self) -> None:
        """Two-part name like 'assessor.parcel_dasymetric_weights' resolves."""
        result = _resolve_model_name("assessor.parcel_dasymetric_weights", self.models)
        assert result == "brewgis.assessor.parcel_dasymetric_weights"

    def test_substring_match(self) -> None:
        """Substring that uniquely matches resolves correctly."""
        result = _resolve_model_name("sacog_parcel_shim", self.models)
        assert result == "brewgis.comparison.sacog_parcel_shim"

    def test_case_insensitive_short_name(self) -> None:
        """Case-insensitive bare name resolves."""
        result = _resolve_model_name("PARCEL_DASYMETRIC_WEIGHTS", self.models)
        assert result == "brewgis.assessor.parcel_dasymetric_weights"

    def test_not_found(self) -> None:
        """Non-existent name raises ModelNotResolvedError."""
        with pytest.raises(ModelNotResolvedError) as excinfo:
            _resolve_model_name("nonexistent_model", self.models)
        msg = str(excinfo.value)
        assert "not found" in msg
        assert "search_models" in msg

    def test_ambiguous_short_name(self) -> None:
        """Ambiguous short name raises ModelNotResolvedError."""
        models = {
            "brewgis.a.foo": object(),
            "brewgis.b.foo": object(),
        }
        with pytest.raises(ModelNotResolvedError) as excinfo:
            _resolve_model_name("foo", models)
        msg = str(excinfo.value)
        assert "ambiguous" in msg
        assert "brewgis.a.foo" in msg
        assert "brewgis.b.foo" in msg

    def test_converts_dot_separated_to_sql_quoted(self) -> None:
        """Unquoted dot-separated FQN resolves via SQL-quoting conversion."""
        models = {
            '"brewgis"."assessor"."parcel_dasymetric_weights"': object(),
        }
        result = _resolve_model_name(
            "brewgis.assessor.parcel_dasymetric_weights", models
        )
        assert result == '"brewgis"."assessor"."parcel_dasymetric_weights"'


class TestExtractPostStatementIndexes:
    """Tests for _extract_post_statement_indexes."""

    def test_parcel_dasymetric_weights(self) -> None:
        """Extracts CREATE INDEX statements from a known model file."""
        indexes = _extract_post_statement_indexes(
            "brewgis.assessor.parcel_dasymetric_weights"
        )
        assert len(indexes) >= 2
        assert any("idx_parcel_dasymetric_weights_apn" in idx for idx in indexes)

    def test_model_with_no_indexes(self) -> None:
        """Returns empty list for models with no post_statements."""
        indexes = _extract_post_statement_indexes(
            "brewgis.comparison.sacog_correlations"
        )
        assert indexes == []

    def test_non_existent_model(self) -> None:
        """Returns empty list for non-existent model files."""
        indexes = _extract_post_statement_indexes("brewgis.assessor.nonexistent_model")
        assert indexes == []

    def test_invalid_fqn(self) -> None:
        """Returns empty list for invalid FQN."""
        indexes = _extract_post_statement_indexes("invalid")
        assert indexes == []


class TestPlanStatsSchema:
    """Tests for PlanStats pydantic schema."""

    def test_basic_creation(self) -> None:
        """PlanStats can be created with basic fields."""
        stats = PlanStats(
            model_name="brewgis.assessor.test",
            total_cost=100.5,
            startup_cost=10.0,
            plan_rows=1000.0,
            node_count=5,
            max_depth=3,
            seq_scans=["test_table (est. 50,000 rows)"],
            nested_loops=1,
        )
        assert stats.model_name == "brewgis.assessor.test"
        assert stats.total_cost == 100.5
        assert stats.node_count == 5

    def test_with_actual_timing(self) -> None:
        """PlanStats can hold actual_total_time from EXPLAIN ANALYZE."""
        stats = PlanStats(
            model_name="brewgis.assessor.test",
            total_cost=100.0,
            startup_cost=5.0,
            plan_rows=1000.0,
            node_count=3,
            max_depth=2,
            seq_scans=[],
            nested_loops=1,
            actual_total_time=45.2,
        )
        assert stats.actual_total_time == 45.2
        assert stats.total_cost == 100.0

    def test_actual_timing_default_none(self) -> None:
        """PlanStats without actual_total_time defaults to None."""
        stats = PlanStats(
            model_name="brewgis.assessor.test",
        )
        assert stats.actual_total_time is None

    def test_error_state(self) -> None:
        """PlanStats can represent an error state."""
        stats = PlanStats(
            model_name="brewgis.assessor.test",
            error="EXPLAIN failed",
        )
        assert stats.error == "EXPLAIN failed"
        assert stats.total_cost is None
        assert stats.seq_scans == []
