# ruff: noqa: ANN201
"""Tests for FilterCompiler — expression tree to SQL WHERE clause."""

from __future__ import annotations

import pytest

from brewgis.workspace.services.filter_compiler import FilterCompiler


@pytest.fixture
def compiler() -> FilterCompiler:
    return FilterCompiler()


class TestColumnFilters:
    """Single column condition compiles correctly."""

    def test_equality(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "land_use", "op": "=", "value": "residential"},
        )
        assert result == "land_use = 'residential'"

    def test_not_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "land_use", "op": "!=", "value": "commercial"},
        )
        assert result == "land_use != 'commercial'"

    def test_greater_than(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "year_built", "op": ">", "value": 2000},
        )
        assert result == "year_built > 2000"

    def test_greater_than_or_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "year_built", "op": ">=", "value": 2000},
        )
        assert result == "year_built >= 2000"

    def test_less_than(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "sqft", "op": "<", "value": 1000},
        )
        assert result == "sqft < 1000"

    def test_less_than_or_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "sqft", "op": "<=", "value": 1500.5},
        )
        assert result == "sqft <= 1500.5"

    def test_like(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "address", "op": "LIKE", "value": "123 Main%"},
        )
        assert result == "address LIKE '123 Main%'"

    def test_in_list(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {
                "type": "column",
                "column": "zoning",
                "op": "IN",
                "value": ["R1", "R2", "R3"],
            },
        )
        assert result == "zoning IN ('R1', 'R2', 'R3')"

    def test_not_in_list(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {
                "type": "column",
                "column": "zoning",
                "op": "NOT IN",
                "value": ["R1", "R2"],
            },
        )
        assert result == "zoning NOT IN ('R1', 'R2')"

    def test_is_null(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "flood_zone", "op": "IS NULL"},
        )
        assert result == "flood_zone IS NULL"

    def test_is_not_null(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "flood_zone", "op": "IS NOT NULL"},
        )
        assert result == "flood_zone IS NOT NULL"


class TestGroupComposition:
    """Group nodes produce parenthesised AND/OR expressions."""

    def test_and_group(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "column",
                        "column": "land_use",
                        "op": "=",
                        "value": "residential",
                    },
                    {
                        "type": "column",
                        "column": "year_built",
                        "op": ">=",
                        "value": 2000,
                    },
                ],
            },
        )
        assert result == "(land_use = 'residential' AND year_built >= 2000)"

    def test_or_group(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {
                "type": "group",
                "operator": "OR",
                "children": [
                    {"type": "column", "column": "zoning", "op": "=", "value": "R1"},
                    {"type": "column", "column": "zoning", "op": "=", "value": "R2"},
                ],
            },
        )
        assert result == "(zoning = 'R1' OR zoning = 'R2')"

    def test_nested_groups(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "column",
                        "column": "land_use",
                        "op": "=",
                        "value": "residential",
                    },
                    {
                        "type": "column",
                        "column": "year_built",
                        "op": ">=",
                        "value": 2000,
                    },
                    {
                        "type": "group",
                        "operator": "OR",
                        "children": [
                            {
                                "type": "column",
                                "column": "zoning",
                                "op": "=",
                                "value": "R1",
                            },
                            {
                                "type": "column",
                                "column": "zoning",
                                "op": "=",
                                "value": "R2",
                            },
                        ],
                    },
                ],
            },
        )
        assert result == (
            "(land_use = 'residential' AND year_built >= 2000"
            " AND (zoning = 'R1' OR zoning = 'R2'))"
        )


class TestEdgeCases:
    """Empty, missing, and degenerate inputs."""

    def test_empty_filter_json(self, compiler: FilterCompiler) -> None:
        assert compiler.compile({}) == ""

    def test_none_filter_json(self, compiler: FilterCompiler) -> None:
        assert compiler.compile(None) == ""

    def test_empty_children_list(self, compiler: FilterCompiler) -> None:
        result = compiler.compile({"type": "group", "operator": "AND", "children": []})
        assert result == ""

    def test_unknown_node_type_raises(self, compiler: FilterCompiler) -> None:
        with pytest.raises(ValueError, match="Unknown node type: bogus"):
            compiler.compile({"type": "bogus"})

    def test_unknown_operator_raises(self, compiler: FilterCompiler) -> None:
        with pytest.raises(ValueError, match="Unknown operator: BOGUS"):
            compiler.compile(
                {"type": "column", "column": "x", "op": "BOGUS", "value": 1},
            )


class TestValueQuoting:
    """Value quoting semantics — types render correctly."""

    def test_numeric_int(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "units", "op": "=", "value": 42},
        )
        assert result == "units = 42"

    def test_numeric_float(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "acres", "op": "=", "value": 3.14},
        )
        assert result == "acres = 3.14"

    def test_text_single_quoted(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "name", "op": "=", "value": "hello"},
        )
        assert result == "name = 'hello'"

    def test_text_escapes_single_quote(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "name", "op": "=", "value": "O'Brien"},
        )
        assert result == "name = 'O''Brien'"

    def test_boolean_true(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "is_active", "op": "=", "value": True},
        )
        assert result == "is_active = true"

    def test_boolean_false(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "is_active", "op": "=", "value": False},
        )
        assert result == "is_active = false"

    def test_none_value(self, compiler: FilterCompiler) -> None:
        result = compiler.compile(
            {"type": "column", "column": "phase", "op": "=", "value": None},
        )
        assert result == "phase = NULL"


class TestIntegrationScenario:
    """Realistic multi-clause expression from the LayerFilter format."""

    def test_complex_scenario(self, compiler: FilterCompiler) -> None:
        """Match the example in the docstring."""
        filter_json = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "column",
                    "column": "land_use",
                    "op": "=",
                    "value": "residential",
                },
                {"type": "column", "column": "year_built", "op": ">=", "value": 2000},
                {
                    "type": "group",
                    "operator": "OR",
                    "children": [
                        {
                            "type": "column",
                            "column": "zoning",
                            "op": "=",
                            "value": "R1",
                        },
                        {
                            "type": "column",
                            "column": "zoning",
                            "op": "=",
                            "value": "R2",
                        },
                    ],
                },
            ],
        }
        result = compiler.compile(filter_json)
        assert result == (
            "(land_use = 'residential' AND year_built >= 2000"
            " AND (zoning = 'R1' OR zoning = 'R2'))"
        )

    def test_single_column_no_group(self, compiler: FilterCompiler) -> None:
        """Top-level column node (no group wrapper) still works."""
        result = compiler.compile(
            {"type": "column", "column": "status", "op": "=", "value": "active"},
        )
        assert result == "status = 'active'"

    def test_in_with_single_value(self, compiler: FilterCompiler) -> None:
        """IN with a non-list value wraps it in a single-element list."""
        result = compiler.compile(
            {"type": "column", "column": "zoning", "op": "IN", "value": "R1"},
        )
        assert result == "zoning IN ('R1')"
