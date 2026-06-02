from __future__ import annotations

from sqlmesh import macro


@macro()
def summarize_metric(evaluator, ref_table: str, column: str) -> str:
    """Generate a scalar subquery to SUM a column from a referenced table.

    Produces::

        (SELECT COALESCE(SUM(<column>), 0) FROM <ref_table>) AS total_<column>

    Usage in model SQL::

        @summarize_metric('core_end_state', 'population')

    Args:
        ref_table: Name of the table/model to query.
        column: Column name to sum.

    Returns:
        SQL scalar subquery expression.
    """
    return f"(SELECT COALESCE(SUM({column}), 0) FROM {ref_table}) AS total_{column}"


@macro()
def coalesce_zero(evaluator, expression: str) -> str:
    """Wrap an expression in COALESCE(..., 0.0) for null safety.

    Usage in model SQL::

        @coalesce_zero('acres_consumed')

    Produces::

        COALESCE(acres_consumed, 0.0)

    Args:
        expression: SQL expression to wrap.

    Returns:
        SQL expression with COALESCE null guard.
    """
    return f"COALESCE({expression}, 0.0)"
