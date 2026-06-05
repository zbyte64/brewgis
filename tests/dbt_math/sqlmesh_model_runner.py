"""Test helper: run a SQLMesh model with synthetic data and return results as a DataFrame.

Uses SQLMesh's Python API (``run_sqlmesh_plan``) internally, so the
exact same SQL that SQLMesh would compile and execute in production is what
runs in the test.  No SQL is duplicated — the SQLMesh model files are the
single source of truth.

Usage::

    from tests.dbt_math.sqlmesh_model_runner import run_model

    df = run_model(
        "fiscal_property_tax",
        upstream={
            "core_end_state": pd.DataFrame({
                "parcel_id": [1, 2],
                "dwelling_units_total": [5.0, 100.0],
                "building_sqft_total": [2000.0, 50000.0],
            }),
        },
        vars_={"target_schema": "public", "scenario_id": "test"},
    )
    assert df["property_tax_revenue"].iloc[0] > 0

The *upstream* dict maps model names (as used in SQLMesh ``ref()``) to
DataFrames.  Each DataFrame is written to a temp table in the environment's
schema.  SQLMesh resolves ``ref('name')`` to that table.  The output table
is read into a DataFrame and returned.

For models that use ``source()`` instead of ``ref()``, use *source_tables*
instead.
"""
# mypy: ignore-errors

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from django.conf import settings

from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan


def run_model(
    model_name: str,
    upstream: dict[str, pd.DataFrame] | None = None,
    source_tables: dict[str, pd.DataFrame] | None = None,
    vars_: dict[str, Any] | None = None,
    *,
    schema_prefix: str = "sqlmesh_test",
    full_refresh: bool = True,
) -> pd.DataFrame:
    """Run a SQLMesh model with synthetic upstream data, return the output table.

    Args:
        model_name: SQLMesh model name (e.g. ``fiscal_property_tax``,
            ``transport.vmt``, or ``analysis/fiscal/fiscal_property_tax``).
        upstream: ``{ref_name: DataFrame}`` for models that use
            ``ref('name')``.  Each DataFrame is written to a temp
            table that SQLMesh resolves to via ``ref()``.
        source_tables: ``{table_name: DataFrame}`` for models that use
            ``source('source_name', 'table_name')``.  Written to the
            schema specified by ``vars_['source_schema']``.
        vars_: Variables passed via SQLMesh plan.  Required keys:
            ``scenario_id``, ``target_schema`` (defaults to the test schema).
        schema_prefix: Prefix for the auto-generated test schema.
        full_refresh: If True, forces a full refresh of the model.

    Returns:
        DataFrame of the model's output table (columns match the model's SQL
        SELECT list).  Returns an empty DataFrame on failure.

    Raises:
        RuntimeError: If SQLMesh execution fails.
    """
    # Normalize model name — strip file extension
    model_name = model_name.replace(".sql", "")
    run_id = uuid.uuid4().hex[:8]
    env_name = f"test_{model_name}_{run_id}"
    test_schema = f"{schema_prefix}_{model_name}_{run_id}"

    upstream = upstream or {}
    source_tables = source_tables or {}
    base_vars = dict(vars_) if vars_ else {}
    base_vars.setdefault("scenario_id", f"test_{run_id}")
    base_vars.setdefault("target_schema", test_schema)

    # ── 1. Create test schema ──────────────────────────────────────
    _ensure_schema(test_schema)

    # ── 2. Write upstream tables ───────────────────────────────────
    # SQLMesh resolves ref('name') using the model's output table name.
    # Upstream data goes into the test schema with scenario-scoped names.
    for ref_name, df in upstream.items():
        tbl = _upstream_table_name(ref_name, run_id)
        _write_df(test_schema, tbl, df)

    # ── 3. Write source tables ─────────────────────────────────────
    source_schema = base_vars.get("source_schema", test_schema)
    if source_schema != test_schema:
        _ensure_schema(source_schema)
    for src_name, df in source_tables.items():
        _write_df(source_schema, src_name, df)

    # ── 4. Run SQLMesh plan ────────────────────────────────────────
    try:
        run_sqlmesh_plan(
            environment=env_name,
            select=[model_name],
            skip_tests=True,
            forward_only=not full_refresh,
        )
    except Exception as e:
        _drop_schema(test_schema)
        if source_schema != test_schema:
            _clean_schema(source_schema, list(source_tables))
        raise e

    # ── 5. Read output table ───────────────────────────────────────
    output_table = f"{model_name}_{run_id}"
    out_df = _read_table(test_schema, output_table)

    # ── 6. Cleanup temp schema ─────────────────────────────────────
    _drop_schema(test_schema)
    if source_schema != test_schema:
        _clean_schema(source_schema, list(source_tables))

    return out_df


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


def _upstream_table_name(ref_name: str, run_id: str) -> str:
    """Return the upstream table name for a given ref.

    SQLMesh stores model output in tables named ``{model_name}_{run_id}``
    within the environment schema, where ``run_id`` acts as the scenario
    discriminator.
    """
    # Models without suffix — use bare name
    if ref_name in ("mode_choice",):
        return ref_name
    return f"{ref_name}_{run_id}"


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

    Handles numpy types (int64, float64) by converting to Python native.
    """
    qualified = f'"{schema}"."{table}"'
    # Build CREATE TABLE from DataFrame dtypes
    col_defs = []
    for col in df.columns:
        dtype = df[col].dtype
        if np.issubdtype(dtype, np.floating):
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
            cols = ", ".join(f'"{c}"' for c in df.columns)
            placeholders = ", ".join(["%s"] * len(df.columns))
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


def _read_table(schema: str, table: str) -> pd.DataFrame:
    """Read a PostGIS table into a DataFrame."""
    qualified = f'"{schema}"."{table}"'
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {qualified}")
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    conn.close()
    return pd.DataFrame(rows, columns=cols)
