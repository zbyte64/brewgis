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
