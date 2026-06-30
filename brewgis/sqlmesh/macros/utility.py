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


@macro()
def snapshot_hash(evaluator) -> str:
    """Return the snapshot version hash suffix of the current physical table.

    ``evaluator.this_model`` resolves to e.g.
    ``"sqlmesh__assessor"."assessor__sacog_assessor_parcels__962285576"``.
    This macro strips the leading identifiers and returns only the 9-digit
    hash after the final ``__``.

    Usage in post_statements::

        CREATE INDEX idx_sacog_assessor_parcels_geometry_@snapshot_hash
        ON @this_model USING GIST (geometry);

    Produces index name e.g. ``idx_sacog_assessor_parcels_geometry_962285576``.
    """
    physical = evaluator.this_model
    # physical is something like '"sqlmesh__assessor"."assessor__sacog_assessor_parcels__962285576"'
    # Extract the last segment after the final __
    last_part = physical.rsplit("__", 1)[-1]
    # Strip any trailing double-quote
    return last_part.rstrip('"')
