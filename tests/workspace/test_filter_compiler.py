"""Tests for FilterCompiler — expression trees to SQL predicates and MapLibre filters.

The SQL form is what an applied filter's layer is materialized from, so it is
tested by the rows it selects: every case compiles a tree and runs it against a
fixed set of rows in Postgres.
"""

# ruff: noqa: ANN201

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.services.filter_compiler import FilterCompiler

# id, land_use, year_built, zoning, flood_zone, "Owner Name"
_ROWS = """
    (1, 'residential', 2005, 'R1', NULL, 'O''Brien'),
    (2, 'commercial', 1990, 'R2', 'AE', 'Acme'),
    (3, NULL, 2010, 'C1', 'X', NULL),
    (4, 'Residential Mixed', NULL, NULL, NULL, 'Lee')
"""


@pytest.fixture
def compiler() -> FilterCompiler:
    return FilterCompiler()


def _ids(tree: dict | None) -> list[int]:
    """The ids of ``_ROWS`` the compiled predicate keeps."""
    where = FilterCompiler().compile(
        tree, source_geom="geometry", local_srid=3310, mpu=1.0
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT src.id FROM (VALUES "  # noqa: S608 (compiled predicate)
            + _ROWS
            + ') AS src(id, land_use, year_built, zoning, flood_zone, "Owner Name") '
            f"WHERE {where} ORDER BY src.id"
        )
        return [row[0] for row in cursor.fetchall()]


def _column(field: str, operator: str, value: object = None, **extra: object) -> dict:
    return {
        "type": "column",
        "field": field,
        "operator": operator,
        "value": value,
        **extra,
    }


@pytest.mark.django_db
class TestSqlColumnConditions:
    """Each operator keeps the rows the map preview's MapLibre filter would."""

    def test_equality(self) -> None:
        assert _ids(_column("land_use", "eq", "residential")) == [1]

    def test_not_equal_keeps_nulls(self) -> None:
        # MapLibre's != matches a feature whose property is missing.
        assert _ids(_column("land_use", "neq", "commercial")) == [1, 3, 4]

    def test_empty_value_compares_as_null(self) -> None:
        assert _ids(_column("flood_zone", "eq", "")) == [1, 4]
        assert _ids(_column("flood_zone", "neq", "")) == [2, 3]

    def test_numeric_comparisons_skip_nulls(self) -> None:
        number = {"value_type": "number"}
        assert _ids(_column("year_built", "gt", "2000", **number)) == [1, 3]
        assert _ids(_column("year_built", "gte", "2005", **number)) == [1, 3]
        assert _ids(_column("year_built", "lt", "2005", **number)) == [2]
        assert _ids(_column("year_built", "lte", "2005", **number)) == [1, 2]

    def test_contains_matches_the_lower_cased_column(self) -> None:
        assert _ids(_column("land_use", "contains", "resid")) == [1, 4]

    def test_null_checks(self) -> None:
        assert _ids(_column("flood_zone", "is_null")) == [1, 4]
        assert _ids(_column("flood_zone", "is_not_null")) == [2, 3]

    def test_membership(self) -> None:
        assert _ids(_column("zoning", "IN", ["R1", "R2"])) == [1, 2]
        # A null zoning is not in the list, so NOT IN keeps it.
        assert _ids(_column("zoning", "NOT IN", ["R1", "R2"])) == [3, 4]
        assert _ids(_column("zoning", "IN", "C1")) == [3]
        assert _ids(_column("zoning", "IN", [])) == []
        assert _ids(_column("zoning", "NOT IN", [])) == [1, 2, 3, 4]

    def test_legacy_node_format(self) -> None:
        legacy = {"type": "column", "column": "year_built", "op": ">=", "value": 2005}
        assert _ids(legacy) == [1, 3]

    def test_quoted_values_and_identifiers_are_literal(self) -> None:
        assert _ids(_column("Owner Name", "eq", "O'Brien")) == [1]
        assert _ids(_column("land_use", "eq", "x' OR '1'='1")) == []


@pytest.mark.django_db
class TestSqlGroups:
    """Groups combine their children with AND/OR, at any depth."""

    def test_and_or_nesting(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                _column("flood_zone", "is_null"),
                {
                    "type": "group",
                    "operator": "OR",
                    "children": [
                        _column("zoning", "eq", "R1"),
                        _column("land_use", "contains", "mixed"),
                    ],
                },
            ],
        }
        assert _ids(tree) == [1, 4]

    def test_empty_trees_keep_every_row(self) -> None:
        assert _ids(None) == [1, 2, 3, 4]
        assert _ids({}) == [1, 2, 3, 4]
        assert _ids({"type": "group", "operator": "AND", "children": []}) == [
            1,
            2,
            3,
            4,
        ]

    def test_empty_children_are_ignored(self) -> None:
        tree = {
            "type": "group",
            "operator": "OR",
            "children": [{}, _column("zoning", "eq", "C1")],
        }
        assert _ids(tree) == [3]


class TestSqlRejectsUnknownInput:
    """Anything that would be spliced into SQL unvalidated is an error."""

    def _compile(self, tree: dict) -> str:
        return FilterCompiler().compile(
            tree, source_geom="geometry", local_srid=3310, mpu=1.0
        )

    def test_unknown_node_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown node type: bogus"):
            self._compile({"type": "bogus"})

    def test_unknown_operator(self) -> None:
        with pytest.raises(ValueError, match="Unknown operator: BOGUS"):
            self._compile(_column("x", "BOGUS", "1"))

    def test_unknown_group_operator(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND TRUE) OR (TRUE",
            "children": [_column("x", "is_null"), _column("y", "is_null")],
        }
        with pytest.raises(ValueError, match="Unknown group operator"):
            self._compile(tree)

    def test_non_finite_number(self) -> None:
        with pytest.raises(ValueError, match="Non-finite number"):
            self._compile(_column("x", "gt", "nan", value_type="number"))


class TestMapLibreCompilation:
    """MapLibre filter expression compilation from editor-format nodes."""

    def test_equality_editor_format(self, compiler: FilterCompiler) -> None:
        """eq operator with field key (editor format)."""
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "existing_du",
                "operator": "eq",
                "value": "0",
                "value_type": "number",
            },
        )
        assert result == ["==", ["get", "existing_du"], 0.0]

    def test_equality_legacy_format(self, compiler: FilterCompiler) -> None:
        """= operator with column/op keys (legacy SQL format)."""
        result = compiler.compile_to_maplibre(
            {"type": "column", "column": "land_use", "op": "=", "value": "residential"},
        )
        assert result == ["==", ["get", "land_use"], "residential"]

    def test_not_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "land_use",
                "operator": "neq",
                "value": "commercial",
            },
        )
        assert result == ["!=", ["get", "land_use"], "commercial"]

    def test_greater_than(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "year_built",
                "operator": "gt",
                "value": "2000",
                "value_type": "number",
            },
        )
        assert result == [">", ["get", "year_built"], 2000.0]

    def test_greater_than_or_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "units",
                "operator": "gte",
                "value": "10",
                "value_type": "number",
            },
        )
        assert result == [">=", ["get", "units"], 10.0]

    def test_less_than(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "sqft",
                "operator": "lt",
                "value": "1000",
                "value_type": "number",
            },
        )
        assert result == ["<", ["get", "sqft"], 1000.0]

    def test_less_than_or_equal(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "acres",
                "operator": "lte",
                "value": "1.5",
                "value_type": "number",
            },
        )
        assert result == ["<=", ["get", "acres"], 1.5]

    def test_is_null(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {"type": "column", "field": "flood_zone", "operator": "is_null"},
        )
        assert result == ["!", ["has", "flood_zone"]]

    def test_is_not_null(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {"type": "column", "field": "flood_zone", "operator": "is_not_null"},
        )
        assert result == ["has", "flood_zone"]

    def test_contains(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "address",
                "operator": "contains",
                "value": "Main",
            },
        )
        assert result == [
            ">=",
            ["index-of", "Main", ["downcase", ["get", "address"]]],
            0,
        ]

    def test_and_group(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "column",
                        "field": "land_use",
                        "operator": "eq",
                        "value": "residential",
                    },
                    {
                        "type": "column",
                        "field": "year_built",
                        "operator": "gte",
                        "value": "2000",
                        "value_type": "number",
                    },
                ],
            },
        )
        assert result == [
            "and",
            ["==", ["get", "land_use"], "residential"],
            [">=", ["get", "year_built"], 2000.0],
        ]

    def test_or_group(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "group",
                "operator": "OR",
                "children": [
                    {
                        "type": "column",
                        "field": "zoning",
                        "operator": "eq",
                        "value": "R1",
                    },
                    {
                        "type": "column",
                        "field": "zoning",
                        "operator": "eq",
                        "value": "R2",
                    },
                ],
            },
        )
        assert result == [
            "or",
            ["==", ["get", "zoning"], "R1"],
            ["==", ["get", "zoning"], "R2"],
        ]

    def test_nested_groups(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "column",
                        "field": "land_use",
                        "operator": "eq",
                        "value": "residential",
                    },
                    {
                        "type": "group",
                        "operator": "OR",
                        "children": [
                            {
                                "type": "column",
                                "field": "zoning",
                                "operator": "eq",
                                "value": "R1",
                            },
                            {
                                "type": "column",
                                "field": "zoning",
                                "operator": "eq",
                                "value": "R2",
                            },
                        ],
                    },
                ],
            },
        )
        assert result == [
            "and",
            ["==", ["get", "land_use"], "residential"],
            ["or", ["==", ["get", "zoning"], "R1"], ["==", ["get", "zoning"], "R2"]],
        ]

    def test_empty_group(self, compiler: FilterCompiler) -> None:
        """Empty children list returns literal true."""
        result = compiler.compile_to_maplibre(
            {"type": "group", "operator": "AND", "children": []},
        )
        assert result == ["literal", True]

    def test_none_filter_json(self, compiler: FilterCompiler) -> None:
        """None or empty filter returns None (no filtering)."""
        assert compiler.compile_to_maplibre(None) is None
        assert compiler.compile_to_maplibre({}) is None

    def test_unknown_node_type_raises(self, compiler: FilterCompiler) -> None:
        with pytest.raises(ValueError, match="Unknown node type: bogus"):
            compiler.compile_to_maplibre({"type": "bogus"})

    def test_unknown_operator_raises(self, compiler: FilterCompiler) -> None:
        with pytest.raises(ValueError, match="Unknown operator: BOGUS"):
            compiler.compile_to_maplibre(
                {"type": "column", "field": "x", "operator": "BOGUS", "value": "1"},
            )

    def test_in_operator(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "zoning",
                "operator": "IN",
                "value": ["R1", "R2", "R3"],
            },
        )
        assert result == ["in", ["get", "zoning"], ["literal", ["R1", "R2", "R3"]]]

    def test_not_in_operator(self, compiler: FilterCompiler) -> None:
        result = compiler.compile_to_maplibre(
            {
                "type": "column",
                "field": "zoning",
                "operator": "NOT IN",
                "value": ["R1", "R2"],
            },
        )
        assert result == ["!", ["in", ["get", "zoning"], ["literal", ["R1", "R2"]]]]

    def test_legacy_sql_operators(self, compiler: FilterCompiler) -> None:
        """Legacy SQL operators still compile to MapLibre."""
        assert compiler.compile_to_maplibre(
            {"type": "column", "column": "x", "op": ">", "value": 5},
        ) == [">", ["get", "x"], 5]
        assert compiler.compile_to_maplibre(
            {"type": "column", "column": "x", "op": "IS NULL"},
        ) == ["!", ["has", "x"]]
        assert compiler.compile_to_maplibre(
            {"type": "column", "column": "x", "op": "IS NOT NULL"},
        ) == ["has", "x"]
        assert compiler.compile_to_maplibre(
            {"type": "column", "column": "x", "op": "LIKE", "value": "Main%"},
        ) == [">=", ["index-of", "Main%", ["downcase", ["get", "x"]]], 0]
