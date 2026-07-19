"""Compiler that converts LayerFilter filter_json trees to SQL WHERE clauses."""

from __future__ import annotations

from typing import Any


class FilterCompiler:
    """Compile LayerFilter expression trees to SQL WHERE clauses."""

    ALLOWED_OPS = {
        "=",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "LIKE",
        "IN",
        "NOT IN",
        "IS NULL",
        "IS NOT NULL",
    }

    def compile(self, filter_json: dict | None) -> str:
        """Compile a filter_json expression tree to a SQL WHERE clause string.

        Args:
            filter_json: The filter expression tree. ``None`` or an empty
                dict returns an empty string.

        Returns:
            SQL WHERE clause fragment (no leading ``WHERE`` keyword).

        Raises:
            ValueError: On unknown node types or operators.
        """
        if not filter_json:
            return ""
        return self._compile_node(filter_json)

    def _compile_node(self, node: dict) -> str:
        node_type = node.get("type")
        if node_type == "column":
            return self._compile_column(node)
        if node_type == "group":
            return self._compile_group(node)
        msg = f"Unknown node type: {node_type}"
        raise ValueError(msg)

    def _compile_column(self, node: dict) -> str:
        column = node["column"]
        op = node["op"]

        if op not in self.ALLOWED_OPS:
            msg = f"Unknown operator: {op}"
            raise ValueError(msg)

        if op in ("IS NULL", "IS NOT NULL"):
            return f"{column} {op}"

        value = node.get("value")

        if op in ("IN", "NOT IN"):
            if not isinstance(value, list):
                value = [value]
            quoted = ", ".join(self._quote_value(v) for v in value)
            return f"{column} {op} ({quoted})"

        return f"{column} {op} {self._quote_value(value)}"

    def _compile_group(self, node: dict) -> str:
        children = node.get("children", [])
        if not children:
            return ""
        operator = node.get("operator", "AND")
        parts = [self._compile_node(c) for c in children]
        joined = f" {operator} ".join(parts)
        return f"({joined})"

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
        msg = f"Unknown node type: {node_type}"
        raise ValueError(msg)

    def _compile_maplibre_column(self, node: dict) -> list:
        # Accept both key formats: "field" (editor) and "column" (legacy SQL)
        column = node.get("field") or node["column"]
        # Accept both key formats: "operator" (editor) and "op" (legacy SQL)
        op = node.get("operator") or node["op"]

        # Comparison operators — accept both naming sets
        comp_map = {
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
        if maplibre_op := comp_map.get(op):
            value = self._coerce_value(node.get("value"), node.get("value_type"))
            return [maplibre_op, ["get", column], value]

        # Special operators
        if op in ("contains", "LIKE", "ILIKE"):
            value = node.get("value", "")
            return [">=", ["index-of", value, ["downcase", ["get", column]]], 0]

        if op in ("is_null", "IS NULL"):
            return ["!", ["has", column]]

        if op in ("is_not_null", "IS NOT NULL"):
            return ["has", column]

        if op in ("IN", "NOT IN"):
            raw_values = node.get("value")
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            inner = ["in", ["get", column], ["literal", values]]
            return ["!", inner] if op == "NOT IN" else inner

        msg = f"Unknown operator: {op}"
        raise ValueError(msg)

    def _compile_maplibre_group(self, node: dict) -> list:
        children = node.get("children", [])
        # Skip empty children (e.g. filters with empty filter_json)
        valid_children = [c for c in children if c and c.get("type")]
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

    @staticmethod
    def _quote_value(value: Any) -> str:
        """Quote a single value for SQL — text gets single-quoted, numbers don't."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"
