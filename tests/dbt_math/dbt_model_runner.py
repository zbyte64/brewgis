"""Test helper: run a dbt model with synthetic data and return results as a DataFrame.

Uses dbt-core's Python API (``DbtRunnerWrapper``) internally, so the
exact same SQL that dbt would compile and execute in production is what
runs in the test.  No SQL is duplicated — the dbt model files are the
single source of truth.

Usage::

    from tests.dbt_math.dbt_model_runner import run_model

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

The *upstream* dict maps ``ref()`` names to DataFrames.  Each DataFrame
is written to a temp table in a dedicated test schema.  dbt resolves
``{{ ref('name') }}`` to that table.  The output table is read into a
DataFrame and returned.

For models that use ``source()`` instead of ``ref()``, use *source_tables*
instead.
"""
# mypy: ignore-errors

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from django.conf import settings

from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper


def run_model(
    model_name: str,
    upstream: dict[str, pd.DataFrame] | None = None,
    source_tables: dict[str, pd.DataFrame] | None = None,
    vars_: dict[str, Any] | None = None,
    *,
    schema_prefix: str = "dbt_test",
    full_refresh: bool = True,
) -> pd.DataFrame:
    """Run a dbt model with synthetic upstream data, return the output table.

    Args:
        model_name: dbt model name (without ``.sql`` extension).
        upstream: ``{ref_name: DataFrame}`` for models that use
            ``{{ ref('name') }}``.  Each DataFrame is written to a temp
            table that dbt resolves to via ``ref()``.
        source_tables: ``{table_name: DataFrame}`` for models that use
            ``{{ source('source_name', 'table_name') }}``.  Written to the
            schema specified by ``vars_['source_schema']``.
        vars_: dbt variables passed via ``--vars``.  Required keys:
            ``scenario_id``, ``target_schema`` (defaults to the test schema).
            Models that read from ``source()`` also need ``source_schema``,
            ``parcel_table``, ``built_form_table``, etc.
        schema_prefix: Prefix for the auto-generated test schema.
        full_refresh: Pass ``--full-refresh`` to dbt (forces table rebuild).

    Returns:
        DataFrame of the model's output table (columns match the model's SQL
        SELECT list).  Returns an empty DataFrame on dbt failure.

    Raises:
        RuntimeError: If dbt execution fails.
    """
    # Allow model_name with or without .sql
    model_name = model_name.replace(".sql", "")
    run_id = uuid.uuid4().hex[:8]
    test_schema = f"{schema_prefix}_{model_name}_{run_id}"

    upstream = upstream or {}
    source_tables = source_tables or {}
    base_vars = dict(vars_) if vars_ else {}
    base_vars.setdefault("scenario_id", f"test_{run_id}")
    base_vars.setdefault("target_schema", test_schema)

    # ── 1. Create test schema ──────────────────────────────────────
    _ensure_schema(test_schema)

    # ── 2. Write upstream tables ───────────────────────────────────
    # dbt resolves ref('name') using the model's alias, not the model
    # filename.  We must write each upstream table with the alias name
    # dbt will look for.
    _ref_table_map: dict[str, str] = {}
    sid = base_vars["scenario_id"]
    for ref_name, df in upstream.items():
        alias_name = _upstream_alias(ref_name, sid)
        tbl = _write_df(test_schema, alias_name, df)
        _ref_table_map[ref_name] = tbl

    # ── 3. Write source tables ─────────────────────────────────────
    source_schema = base_vars.get("source_schema", test_schema)
    if source_schema != test_schema:
        _ensure_schema(source_schema)
    for src_name, df in source_tables.items():
        _write_df(source_schema, src_name, df)

    # ── 4. Add ref table names as vars so models can find them ─────
    # Some models use source() with dynamic table names from vars.
    # If upstream tables exist, dbt resolves ref() via the test schema.
    base_vars.setdefault("source_schema", source_schema)

    # ── 5. Run dbt ─────────────────────────────────────────────────
    runner = DbtRunnerWrapper()
    result = runner.run(
        select=[model_name],
        vars_=base_vars,
        full_refresh=full_refresh,
        db_name=settings.DATABASES["default"]["NAME"],
    )
    if not result.success:
        _drop_schema(test_schema)
        if source_schema != test_schema:
            _clean_schema(source_schema, list(source_tables))
        raise RuntimeError(
            f"dbt model '{model_name}' failed: {result.error or result.results}"
        )

    # ── 6. Read output table ───────────────────────────────────────
    output_table = base_vars.get("alias", f"{model_name}_{sid}")
    out_df = _read_table(test_schema, output_table)

    # ── 7. Cleanup temp schema ─────────────────────────────────────
    _drop_schema(test_schema)
    if source_schema != test_schema:
        _clean_schema(source_schema, list(source_tables))

    return out_df


# ── Internal helpers ────────────────────────────────────────────────


def _get_conn() -> psycopg.Connection:
    """Return a raw psycopg connection (outside Django's transaction).

    The ``@pytest.mark.django_db`` marker wraps tests in a transaction.
    dbt connects via its own connection and cannot see uncommitted data
    written through Django's ``connection`` cursor.  Using a raw psycopg
    connection ensures data is visible to dbt's separate connection.
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


def _upstream_alias(ref_name: str, scenario_id: str) -> str:
    """Return the dbt alias for an upstream model, given a scenario_id.

    dbt resolves ``ref('model_name')`` using the resolved alias from the
    model's ``{{ config(alias=…) }}``, not the model filename.  When a test
    writes upstream data manually, the table must use the alias name.

    Known alias patterns:
        ``core_end_state``   → ``end_state_{scenario_id}``
                            (custom SQL alias config)
        ``mode_choice``       → ``mode_choice``
                            (no custom alias — uses filename)
        ``trip_distribution`` → ``trip_distribution``
                            (no custom alias — uses filename)

    All other SQL models follow the convention ``{model_name}_{scenario_id}``.
    """
    # Models with no custom alias — dbt uses the model filename.
    if ref_name in ("mode_choice", "trip_distribution"):
        return ref_name
    # Special-case: core_end_state uses a different prefix from its filename.
    if ref_name == "core_end_state":
        return f"end_state_{scenario_id}"
    return f"{ref_name}_{scenario_id}"


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
                    None if pd.isna(v) else
                    bool(v) if isinstance(v, (bool, np.bool_)) else
                    int(v) if isinstance(v, (int, np.integer)) else
                    float(v) if isinstance(v, (float, np.floating)) else
                    v
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