"""Step definitions for SQLMesh isolation BDD scenarios.

Each step interacts with PostGIS via a raw psycopg connection
(``db_conn`` fixture, autocommit=True) so that tables are immediately
visible to SQLMesh's separate database connection.
"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

# Register the feature file so pytest-bdd discovers scenarios.
scenarios(str(Path(__file__).parent.parent / "dbt_isolation.feature"))


# ── Helpers ────────────────────────────────────────────────────────────


def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier for safe interpolation."""
    return f'"{name}"'


# ── Given steps ────────────────────────────────────────────────────────
@given("idle dbt connections are terminated")
def idle_connections_terminated(
    scenario_context: dict,
    db_conn,
) -> None:
    """Terminate all other connections to the test database."""
    with db_conn.cursor() as cursor:
        cursor.execute("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
        """)


@given(parsers.parse('schema "{schema_name}" exists'))
def schema_exists(
    schema_name: str,
    scenario_context: dict,
    db_conn,
) -> None:
    """Create schema if it does not already exist."""
    ident = _quote_ident(schema_name)
    with db_conn.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {ident}")


@given(parsers.parse('schema "{schema_name}" does not exist'))
def schema_does_not_exist(
    schema_name: str,
    scenario_context: dict,
    db_conn,
) -> None:
    """Ensure schema does not exist (drop if present)."""
    ident = _quote_ident(schema_name)
    with db_conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {ident} CASCADE")


@given(
    parsers.parse(
        'a parcel table "{table_name}" exists in schema "{schema}"',
    )
)
def parcel_table_exists(
    table_name: str,
    schema: str,
    scenario_context: dict,
    db_conn,
) -> None:
    """Create a PostGIS parcel table with one test polygon.

    Stores ``parcel_table`` in context so the When step knows which
    table to target.
    """
    schema_q = _quote_ident(schema)
    table_q = _quote_ident(table_name)
    full_name = f"{schema_q}.{table_q}"

    with db_conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {full_name} (
                id SERIAL PRIMARY KEY,
                geom GEOMETRY(POLYGON, 4326)
            )
            """
        )
        cursor.execute(
            f"INSERT INTO {full_name} (geom) "
            f"VALUES (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326))"
        )

    # Track for cleanup
    scenario_context["parcel_table"] = (schema, table_name)
    scenario_context.setdefault("cleanup", []).append(
        {"type": "table", "schema": schema, "name": table_name}
    )


# ── When steps ─────────────────────────────────────────────────────────


def _run_sqlmesh_and_store_result(
    module: str,
    scenario_id: str,
    target_schema: str,
    scenario_context: dict,
) -> None:
    """Invoke SQLMesh and store the result in scenario context."""
    environment = f"bdd_{scenario_id}"

    result = run_sqlmesh_plan(
        environment=environment,
        select=[module],
        skip_tests=True,
    )

    scenario_context["sqlmesh_result"] = result

    # Register SQLMesh-created view for cleanup
    view_name = f"{module}_{scenario_id}"
    scenario_context.setdefault("cleanup", []).append(
        {"type": "view", "schema": target_schema, "name": view_name}
    )


@when(
    parsers.parse(
        'I run dbt module "{module}" with scenario_id "{scenario_id}" '
        'in schema "{target_schema}"',
    )
)
def run_dbt_module(
    module: str,
    scenario_id: str,
    target_schema: str,
    scenario_context: dict,
) -> None:
    """Run a single SQLMesh model with the given vars."""
    _run_sqlmesh_and_store_result(module, scenario_id, target_schema, scenario_context)


@when(
    parsers.parse(
        'I run dbt module "{module}" with scenario_id "{scenario_id}" '
        'in schema "{target_schema}" a second time',
    )
)
def run_dbt_module_second(
    module: str,
    scenario_id: str,
    target_schema: str,
    scenario_context: dict,
) -> None:
    """Run the same SQLMesh model a second time (idempotency check)."""
    _run_sqlmesh_and_store_result(module, scenario_id, target_schema, scenario_context)


# ── Then steps ─────────────────────────────────────────────────────────


@then(parsers.parse('a view named "{view_name}" should exist in schema "{schema}"'))
def view_exists(
    view_name: str,
    schema: str,
    scenario_context: dict,
    db_conn,
) -> None:
    """Assert that a view exists in the given schema."""
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
            )
            """,
            [schema, view_name],
        )
        exists = cursor.fetchone()[0]
    assert exists, f"View '{view_name}' not found in schema '{schema}'"


@then(parsers.parse('no view named "{view_name}" should exist in schema "{schema}"'))
def view_does_not_exist(
    view_name: str,
    schema: str,
    scenario_context: dict,
    db_conn,
) -> None:
    """Assert that a view does NOT exist in the given schema."""
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
            )
            """,
            [schema, view_name],
        )
        exists = cursor.fetchone()[0]
    assert not exists, f"View '{view_name}' unexpectedly found in schema '{schema}'"


@then("the dbt run should have succeeded")
def dbt_run_succeeded(scenario_context: dict) -> None:
    """Assert that the last SQLMesh run completed successfully."""
    result = scenario_context.get("sqlmesh_result")
    assert result is not None, "No SQLMesh result stored — did the When step run?"
    assert result.success, f"SQLMesh run failed: {result.error}"


@then("the dbt run should have failed")
def dbt_run_failed(scenario_context: dict) -> None:
    """Assert that the last SQLMesh run failed."""
    result = scenario_context.get("sqlmesh_result")
    assert result is not None, "No SQLMesh result stored — did the When step run?"
    assert not result.success, "Expected SQLMesh run to fail, but it succeeded."
