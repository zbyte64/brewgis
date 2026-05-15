"""Tests for the static column provenance checker.

Tests the contract resolution layer and provenance checker core
without requiring a running Postgres or dbt manifest.
"""

from __future__ import annotations

from brewgis.workspace.dagster.check_provenance import ProvenanceError
from brewgis.workspace.dagster.check_provenance import resolve_inline


class TestResolveInline:
    """``resolve_inline`` is an identity function."""

    def test_identity(self) -> None:
        """Returns the same frozenset passed in."""
        cols = frozenset({"a", "b", "c"})
        assert resolve_inline(cols) is cols


class TestProvenanceError:
    """``ProvenanceError`` dataclass and helpers."""

    def test_basic_error(self) -> None:
        """ProvenanceError stores all fields."""
        err = ProvenanceError(
            downstream="core_end_state",
            upstream="base_canvas_etl",
            missing=frozenset({"gross_acres"}),
            upstream_source="baseschema",
            downstream_source="dbt:core_end_state",
            suggestion="check renaming",
        )
        assert str(err.downstream) == "core_end_state"
        assert str(err.upstream) == "base_canvas_etl"
        assert err.missing == frozenset({"gross_acres"})
        assert err.upstream_source == "baseschema"
        assert err.downstream_source == "dbt:core_end_state"
        assert err.suggestion == "check renaming"

    def test_minimal_error(self) -> None:
        """ProvenanceError without optional fields."""
        err = ProvenanceError(
            downstream="a",
            upstream="b",
            missing=frozenset({"x"}),
            upstream_source="soda:test",
        )
        assert err.downstream_source is None
        assert err.suggestion is None
