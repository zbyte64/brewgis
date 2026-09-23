"""Test helper: run a SQLMesh model with synthetic data and return results as a DataFrame.

Uses SQLMesh's Python API (``run_sqlmesh_plan``) internally, so the
exact same SQL that SQLMesh would compile and execute in production is what
runs in the test.  No SQL is duplicated — the SQLMesh model files are the
single source of truth.

Usage::

    from tests.dbt_math.sqlmesh_model_runner import run_model

    df = run_model(
        "core_end_state",
        upstream={"base_canvas": pd.DataFrame({...})},
    )

The *upstream* dict maps the names the model reads to DataFrames.  Each
DataFrame is written into the run's ``scenario_schema`` under exactly that name,
and the model under test is selected by its fully-qualified name
(``brewgis.<scenario_schema>.<model>``).

Analysis models are *blueprinted*: SQLMesh renders one instance per analyzed
scenario, named from rows in the database
(``sqlmesh/macros/analysis_blueprints.py``). A blueprinted model with an empty
``blueprints`` list does not load at all, so a test database with no analyzed
scenario cannot load the project — the ``parity_scenario`` fixture (see
``conftest.py``) commits the two scenario rows the two providers need and
returns the ``ascn<scenario_pk>`` schema this runner materializes into.

The rendered model definitions are cached on disk per model-file mtime, and a
blueprint is baked into what gets cached — so each run renders into a private
cache directory (the same fix ``pipeline.run_modules_sync`` applies) rather than
inheriting the project's.

For models that use ``source()`` instead of ``ref()``, use *source_tables*
instead.
"""
# mypy: ignore-errors

from __future__ import annotations

import shutil
import tempfile
import uuid
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from django.conf import settings

from brewgis.workspace.analysis.sqlmesh_runner import get_context
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

# Every run promotes into this environment. Models are selected by their
# per-run FQN, so nothing collides between runs.
_ENVIRONMENT = "prod"


def run_model(
    model_name: str,
    upstream: dict[str, pd.DataFrame] | None = None,
    source_tables: dict[str, pd.DataFrame] | None = None,
    vars_: dict[str, Any] | None = None,
    *,
    scenario_schema: str,
    schema_prefix: str = "sqlmesh_test",
    full_refresh: bool = True,
) -> pd.DataFrame:
    """Run a SQLMesh model with synthetic upstream data, return the output table.

    Args:
        model_name: Bare SQLMesh model name (e.g. ``fiscal_property_tax``,
            ``vmt``, ``mode_choice``) — the name the model's file gives it.
        upstream: ``{read_name: DataFrame}`` for the scenario-schema tables the
            model selects from (e.g. ``{"trip_distribution": df}`` for a model
            that reads ``@{scenario_schema}.trip_distribution``). Each DataFrame
            is written into *scenario_schema* under exactly that name.
        source_tables: ``{table_name: DataFrame}`` for models that use
            ``source('source_name', 'table_name')``.  Written to the
            schema specified by ``vars_['source_schema']``.
        vars_: Extra SQLMesh config variables.
        scenario_schema: The analyzed scenario's schema the run's blueprint
            renders into (``ascn<scenario_pk>``), from the ``parity_scenario``
            fixture. Upstream tables and the model's own output live there, and
            it is dropped afterwards.
        schema_prefix: Prefix for the scratch schema the ``source_tables`` land in.
        full_refresh: If True, the plan may backfill rather than run
            forward-only.

    Returns:
        DataFrame of the model's output (columns match the model's SELECT list).

    Raises:
        RuntimeError: If SQLMesh execution fails.
    """
    model_name = model_name.replace(".sql", "").rsplit("/", 1)[-1]
    run_id = uuid.uuid4().hex[:8]
    scratch_schema = f"{schema_prefix}_{model_name}_{run_id}"
    # The model's name under the scenario's blueprint: SQLMesh names a
    # blueprinted model ``brewgis.<scenario_schema>.<model_table>``.
    model_fqn = f"brewgis.{scenario_schema}.{model_name}"

    upstream = upstream or {}
    source_tables = source_tables or {}
    base_vars = dict(vars_) if vars_ else {}
    source_schema = base_vars.get("source_schema", scratch_schema)

    # A private cache per run: the rendered model definitions are cached on disk
    # keyed by model-file mtime, so a shared cache would serve a previous run's
    # blueprint-derived model names — this run's scenario has its own schema, so
    # those names differ and the load fails with "Duplicate SQL model name".
    cache_dir = tempfile.mkdtemp(prefix="brewgis-sqlmesh-parity-cache-")
    try:
        _ensure_schema(scenario_schema)
        _ensure_schema(scratch_schema)
        if source_schema != scratch_schema:
            _ensure_schema(source_schema)
        for ref_name, df in upstream.items():
            _write_df(scenario_schema, ref_name, df)
        for src_name, df in source_tables.items():
            _write_df(source_schema, src_name, df)

        # `select` takes the FQN, not the bare name: every scenario has its own
        # instance of the model, and only this scenario's blueprint reads this
        # scenario's schema.
        run_sqlmesh_plan(
            environment=_ENVIRONMENT,
            select=[model_fqn],
            skip_tests=True,
            forward_only=not full_refresh,
            variables=base_vars,
            cache_dir=cache_dir,
        )
        return _read_model(model_fqn, cache_dir)
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)
        # Drop the scenario's schema (upstream tables included) so the next
        # run's plan cannot reuse a physical table this run materialized.
        _drop_schema(scenario_schema)
        _drop_schema(scratch_schema)
        if source_schema != scratch_schema:
            _clean_schema(source_schema, list(source_tables))


def _read_model(model_fqn: str, cache_dir: str) -> pd.DataFrame:
    """Read a materialized model's rows, resolving its physical table name.

    The physical object is ``{schema}__{table}__{version}``, so it cannot be
    guessed from the model name; ``resolve_table`` is the same lookup the model
    code itself uses.  Read through a context of its own because
    ``run_sqlmesh_plan`` closes the one it planned with.
    """
    context = get_context(cache_dir=cache_dir)
    try:
        return context.fetchdf(f"SELECT * FROM {context.resolve_table(model_fqn)}")
    finally:
        for adapter in (context.engine_adapters or {}).values():
            adapter.close()
        context.close()


# ── Internal helpers ────────────────────────────────────────────────


def _get_conn() -> psycopg.Connection:
    """Return a raw psycopg connection (outside Django's transaction).

    The ``@pytest.mark.django_db`` marker wraps tests in a transaction.
    SQLMesh connects via its own connection and cannot see uncommitted data
    written through Django's ``connection`` cursor.  Using a raw psycopg
    connection ensures data is visible to SQLMesh's separate connection.
    """
    db = settings.DATABASES["default"]
    return psycopg.connect(
        host=db.get("HOST", "localhost"),
        port=db.get("PORT", "5432"),
        user=db.get("USER", ""),
        password=db.get("PASSWORD", ""),
        dbname=db.get("NAME", "brewgis"),
    )


def _ensure_schema(schema: str) -> None:
    """Create schema if it doesn't exist."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    conn.commit()
    conn.close()


def _drop_schema(schema: str) -> None:
    """Drop schema and all its objects (CASCADE)."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    conn.commit()
    conn.close()


def _clean_schema(schema: str, table_names: list[str]) -> None:
    """Drop specific tables from a schema (cleanup shared schema)."""
    conn = _get_conn()
    with conn.cursor() as cur:
        for tbl in table_names:
            cur.execute(f'DROP TABLE IF EXISTS "{schema}"."{tbl}" CASCADE')
    conn.commit()
    conn.close()


def _write_df(schema: str, table: str, df: pd.DataFrame) -> str:
    """Write a DataFrame to a PostGIS table. Returns ``schema.table``.

    Handles numpy types (int64, float64) by converting to Python native. A
    ``geometry`` column is WKT text in the DataFrame and is written as a real
    PostGIS geometry, because models that copy such a column into their own
    output index it with GIST — which a ``text`` column rejects.
    """
    qualified = f'"{schema}"."{table}"'
    # Build CREATE TABLE from DataFrame dtypes
    col_defs = []
    geometry_columns = set()
    for col in df.columns:
        dtype = df[col].dtype
        if col == "geometry":
            geometry_columns.add(col)
            col_defs.append(f'"{col}" GEOMETRY(Geometry, 4326)')
        elif np.issubdtype(dtype, np.floating):
            col_defs.append(f'"{col}" DOUBLE PRECISION')
        elif np.issubdtype(dtype, np.integer):
            col_defs.append(f'"{col}" INTEGER')
        elif np.issubdtype(dtype, np.bool_):
            col_defs.append(f'"{col}" BOOLEAN')
        else:
            col_defs.append(f'"{col}" TEXT')
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {qualified}")
        cur.execute(f"CREATE UNLOGGED TABLE {qualified} ({', '.join(col_defs)})")
        # Batch insert
        if len(df) > 0:
            columns = list(df.columns)
            cols = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join(
                "ST_GeomFromText(%s, 4326)" if c in geometry_columns else "%s"
                for c in columns
            )
            for row in df.itertuples(index=False):
                vals = tuple(
                    None
                    if pd.isna(v)
                    else bool(v)
                    if isinstance(v, (bool, np.bool_))
                    else int(v)
                    if isinstance(v, (int, np.integer))
                    else float(v)
                    if isinstance(v, (float, np.floating))
                    else v
                    for v in row
                )
                cur.execute(
                    f"INSERT INTO {qualified} ({cols}) VALUES ({placeholders})",
                    vals,
                )
    conn.commit()
    conn.close()
    return qualified
