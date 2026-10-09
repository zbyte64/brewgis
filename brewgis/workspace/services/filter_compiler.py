"""Compile LayerFilter ``filter_json`` trees to SQL and to MapLibre expressions.

The SQL form is what an applied filter's layer is materialized from
(``models/spatial_filter/spatial_filter.py``): every node — columns and spatial
conditions alike — becomes one ``WHERE`` predicate over the filtered layer's
rows, aliased ``src``. The MapLibre form only drives the filter editor's
"preview on map", which can evaluate column conditions alone.

Both targets read the two node formats the editor and older callers write: the
editor's ``{"field", "operator": "eq", "value", "value_type"}`` and the legacy
``{"column", "op": "=", "value"}``. The SQL form mirrors the MapLibre semantics
the preview shows, null handling included: ``eq``/``neq`` compare with
``IS [NOT] DISTINCT FROM`` (a missing tile property equals ``null`` and differs
from every value), ``contains`` looks for the value in the lower-cased column
text, and ``NOT IN`` keeps rows whose column is null.
"""

from __future__ import annotations

import math
from typing import Any

from brewgis.workspace.services.spatial_filter import SPATIAL_NODE_TYPE
from brewgis.workspace.services.spatial_filter import quote_ident
from brewgis.workspace.services.spatial_filter import spatial_predicate

# Comparison operators in both node formats, mapped to each target's spelling.
_MAPLIBRE_COMPARISONS = {
    "eq": "==",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "=": "==",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}
_SQL_COMPARISONS = {
    "eq": "IS NOT DISTINCT FROM",
    "neq": "IS DISTINCT FROM",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "=": "IS NOT DISTINCT FROM",
    "!=": "IS DISTINCT FROM",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}
_CONTAINS_OPS = frozenset({"contains", "LIKE", "ILIKE"})
_IS_NULL_OPS = frozenset({"is_null", "IS NULL"})
_IS_NOT_NULL_OPS = frozenset({"is_not_null", "IS NOT NULL"})
_MEMBERSHIP_OPS = frozenset({"IN", "NOT IN"})
_GROUP_OPERATORS = frozenset({"AND", "OR"})

# Alias the materialized model gives the filtered layer's rows.
_ROW_ALIAS = "src"


class FilterCompiler:
    """Compile LayerFilter expression trees to SQL predicates and MapLibre filters."""

    # ── SQL predicate compilation ──────────────────────────────

    def compile(
        self,
        filter_json: dict | None,
        *,
        source_geom: str,
        local_srid: int,
        mpu: float,
    ) -> str:
        """Compile *filter_json* to a SQL predicate over the rows aliased ``src``.

        *source_geom* is the filtered layer's geometry column; *local_srid* and
        *mpu* (``macros.geometry.metres_per_unit``) are the region's projection
        and its metres-per-unit factor, used by spatial conditions. Every
        ``spatial`` node must carry its resolved projection model
        (``services.spatial_filter.FILTER_REF_KEY``).

        An empty tree, or a group with no conditions, is ``TRUE`` — the
        identity of a filter, as in the MapLibre form.

        Raises:
            ValueError: On an unknown node type, operator or group operator, or
                a non-finite number.
        """
        if not filter_json:
            return "TRUE"
        return self._sql_node(
            filter_json, source_geom=source_geom, local_srid=local_srid, mpu=mpu
        )

    def _sql_node(
        self, node: dict, *, source_geom: str, local_srid: int, mpu: float
    ) -> str:
        node_type = node.get("type")
        if node_type == "column":
            return self._sql_column(node)
        if node_type == SPATIAL_NODE_TYPE:
            return spatial_predicate(
                node, source_geom=source_geom, local_srid=local_srid, mpu=mpu
            )
        if node_type == "group":
            children = [c for c in node.get("children") or [] if c and c.get("type")]
            if not children:
                return "TRUE"
            operator = _group_operator(node)
            parts = [
                self._sql_node(
                    child, source_geom=source_geom, local_srid=local_srid, mpu=mpu
                )
                for child in children
            ]
            return f"({f' {operator} '.join(parts)})"
        msg = f"Unknown node type: {node_type}"
        raise ValueError(msg)

    def _sql_column(self, node: dict) -> str:
        column = f"{_ROW_ALIAS}.{quote_ident(str(node.get('field') or node['column']))}"
        op = node.get("operator") or node["op"]

        if sql_op := _SQL_COMPARISONS.get(op):
            value = self._coerce_value(node.get("value"), node.get("value_type"))
            return f"{column} {sql_op} {_sql_literal(value)}"
        if op in _CONTAINS_OPS:
            value = str(node.get("value", ""))
            return f"strpos(lower({column}::text), {_sql_literal(value)}) > 0"
        if op in _IS_NULL_OPS:
            return f"{column} IS NULL"
        if op in _IS_NOT_NULL_OPS:
            return f"{column} IS NOT NULL"
        if op in _MEMBERSHIP_OPS:
            raw_values = node.get("value")
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            if not values:
                return "FALSE" if op == "IN" else "TRUE"
            listed = ", ".join(_sql_literal(v) for v in values)
            member = f"COALESCE({column} IN ({listed}), FALSE)"
            return f"NOT {member}" if op == "NOT IN" else member
        msg = f"Unknown operator: {op}"
        raise ValueError(msg)

    # ── MapLibre filter expression compilation ─────────────────

    def compile_to_maplibre(self, filter_json: dict | None) -> list | None:
        """Compile a filter_json expression tree to a MapLibre filter expression.

        Returns None if the filter is empty (no filtering). Returns a MapLibre
        filter expression list otherwise.
        """
        if not filter_json:
            return None
        return self._compile_maplibre_node(filter_json)

    def _compile_maplibre_node(self, node: dict) -> list:
        if not node:
            return ["literal", True]
        node_type = node.get("type")
        if node_type == "column":
            return self._compile_maplibre_column(node)
        if node_type == "group":
            return self._compile_maplibre_group(node)
        if node_type == SPATIAL_NODE_TYPE:
            # A spatial predicate has no MapLibre expression — a tile feature
            # cannot be intersected with another layer's geometry client-side.
            # It is only evaluated in the materialized filtered layer, so the
            # preview leaves it out.
            return ["literal", True]
        msg = f"Unknown node type: {node_type}"
        raise ValueError(msg)

    def _compile_maplibre_column(self, node: dict) -> list:
        # Accept both key formats: "field" (editor) and "column" (legacy SQL)
        column = node.get("field") or node["column"]
        # Accept both key formats: "operator" (editor) and "op" (legacy SQL)
        op = node.get("operator") or node["op"]

        if maplibre_op := _MAPLIBRE_COMPARISONS.get(op):
            value = self._coerce_value(node.get("value"), node.get("value_type"))
            return [maplibre_op, ["get", column], value]

        # Special operators
        if op in _CONTAINS_OPS:
            value = node.get("value", "")
            return [">=", ["index-of", value, ["downcase", ["get", column]]], 0]

        if op in _IS_NULL_OPS:
            return ["!", ["has", column]]

        if op in _IS_NOT_NULL_OPS:
            return ["has", column]

        if op in _MEMBERSHIP_OPS:
            raw_values = node.get("value")
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            inner = ["in", ["get", column], ["literal", values]]
            return ["!", inner] if op == "NOT IN" else inner

        msg = f"Unknown operator: {op}"
        raise ValueError(msg)

    def _compile_maplibre_group(self, node: dict) -> list:
        children = node.get("children", [])
        # Skip empty children (e.g. filters with empty filter_json) and spatial
        # children, which the preview cannot evaluate (an always-true literal
        # would only pad the expression).
        valid_children = [
            c
            for c in children
            if c and c.get("type") and c.get("type") != SPATIAL_NODE_TYPE
        ]
        if not valid_children:
            return ["literal", True]
        operator = node.get("operator", "AND")
        parts = [self._compile_maplibre_node(c) for c in valid_children]
        return [operator.lower(), *parts]

    @staticmethod
    def _coerce_value(value: Any, value_type: str | None = None) -> Any:
        """Coerce a filter value to the correct Python type for MapLibre."""
        if value is None or value == "":
            return None
        if value_type == "number":
            return float(value)
        return value


def _group_operator(node: dict) -> str:
    """Return a group's ``AND``/``OR``, rejecting anything else (it is spliced into SQL)."""
    operator = str(node.get("operator", "AND")).upper()
    if operator not in _GROUP_OPERATORS:
        msg = f"Unknown group operator: {operator}"
        raise ValueError(msg)
    return operator


def _sql_literal(value: Any) -> str:
    """Render *value* as a SQL literal — text single-quoted, numbers bare."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            msg = f"Non-finite number in filter: {value}"
            raise ValueError(msg)
        return repr(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"
