from __future__ import annotations

import sqlglot.expressions as exp
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
def snapshot_hash(evaluator, prefix: str) -> str:
    """Return ``prefix`` suffixed with the current snapshot's version hash.

    The hash is the version suffix of the physical table, e.g.
    ``"sqlmesh__fresno"."fresno__parcel_shim__1116429613"`` → ``1116429613``.

    Usage in pre/post statements — **the call form is mandatory**::

        CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcel_shim_geometry_')
        ON @this_model USING GIST (geometry);

    Produces the index name ``idx_parcel_shim_geometry_1116429613``.

    The bare form (``idx_x_@snapshot_hash``) is **not** a macro call. SQLMesh
    resolves bare ``@name`` tokens only against blueprint/config variables
    (``MacroEvaluator.template``); the ``@macro()`` registry is reached solely
    through ``@name(...)``. A bare placeholder therefore lands in the DDL
    verbatim, every snapshot writes the same index name, and ``CREATE INDEX IF
    NOT EXISTS`` creates it on the first snapshot's table only — every later
    version, including the one backing the model view, silently skips it. The
    linter rule ``SnapshotHashIndexName`` flags that spelling.

    ``prefix`` must be literal text: an ``@{var}`` / ``@var`` placeholder inside
    the string argument is **not** expanded (string literals are not walked by
    the variable resolver, and SQLMesh drops variables that a model references
    only in its name or statements), so it would end up verbatim in the index
    name. Region prefixes are unnecessary — index names are scoped to the
    physical schema (``sqlmesh__fresno`` / ``sqlmesh__sacog``).

    Args:
        prefix: Index-name prefix ending in ``_``, e.g.
            ``'idx_parcel_shim_geometry_'``.

    Returns:
        ``prefix`` suffixed with the version hash of ``@this_model``.
    """
    physical = evaluator.this_model
    # physical is something like '"sqlmesh__fresno"."fresno__parcel_shim__1116429613"'
    # Extract the last segment after the final __ and strip any trailing double-quote
    suffix = physical.rsplit("__", 1)[-1].rstrip('"')
    return f"{prefix}{suffix}"


@macro()
def ref_model(evaluator, model_fqn: str) -> exp.Expression:
    """Convert a dotted model FQN into a proper 3-part ``exp.Table`` reference.

    SQLMesh's ``@var`` expansion wraps strings via ``exp.convert()``, which
    serializes the value as a SQL literal.  When the literal contains dots
    (e.g. ``'brewgis.assessor.parcel_partition_stats'``), it re-parses as a
    *single* quoted identifier with embedded dots instead of a 3-part table
    reference.  ``find_tables()`` then normalises it to
    ``'"brewgis.assessor.parcel_partition_stats"'``, which does not match
    the model's ``fqn`` — so the dependency is **not** tracked in
    ``snapshot.parents``.

    This macro returns a proper ``exp.Table`` AST node (3-part qualified),
    so that ``find_tables()`` produces the canonical 3-part quoted form
    ``'"brewgis"."assessor"."parcel_partition_stats"'`` which **is**
    correctly resolved by the dependency tracker.

    Usage in model SQL::

        FROM @ref_model(@parcel_known_features_model) kf
        LEFT JOIN @ref_model(@parcel_partition_stats_model) ps ON ...

    The ``@xxx_model`` variables are defined in ``config.py`` and can be
    overridden in test / comparison environments for isolation.

    Args:
        model_fqn: Three-part fully qualified model name
            (e.g. ``"brewgis.assessor.parcel_known_features"``).

    Returns:
        A 3-part ``exp.Table`` expression.
    """
    parts = model_fqn.rstrip('"').split(".")
    if len(parts) >= 3:
        return exp.Table(
            this=exp.to_identifier(parts[2]),
            db=exp.to_identifier(parts[1]),
            catalog=exp.to_identifier(parts[0]),
        )
    if len(parts) == 2:
        return exp.Table(
            this=exp.to_identifier(parts[1]), db=exp.to_identifier(parts[0])
        )
    return exp.Table(this=exp.to_identifier(parts[0]))
