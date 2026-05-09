"""pytest fixtures for dbt isolation BDD tests.

Provides raw psycopg DB connections (bypassing Django's test transaction)
for all steps. Does NOT import from tests/e2e/.

Each step manages its own connection via a shared ``db_conn`` fixture
so that tables and views created by one step are immediately visible
to dbt (which uses its own connection) and to subsequent steps.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
import pytest
from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import Any

# All tests in this directory require a running PostGIS instance.
pytestmark = [
    pytest.mark.integration,
]


def _connect() -> Any:
    """Open a raw psycopg connection to the test database.

    Sets a 10-second statement timeout so no DDL hangs indefinitely
    if there is a lingering lock from a concurrent test.
    """
    db_conf = settings.DATABASES["default"]
    conn = psycopg.connect(
        host=db_conf["HOST"],
        port=db_conf["PORT"],
        dbname=db_conf["NAME"],
        user=db_conf["USER"],
        password=db_conf["PASSWORD"],
        autocommit=True,
    )
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '10s'")
    return conn


@pytest.fixture
def db_conn() -> Generator[Any, None, None]:
    """Provide a raw psycopg connection for the duration of a test.

    The connection is ``autocommit=True`` so all DDL/DML is immediately
    visible to dbt's separate database connection. The connection is
    closed after the test.
    """
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _run_cleanup(ctx: dict[str, Any]) -> None:
    """Execute accumulated cleanup actions in reverse order."""
    try:
        conn = _connect()
    except Exception:  # noqa: BLE001
        return

    with conn.cursor() as cursor:
        for item in reversed(ctx.get("cleanup", [])):
            kind = item["type"]
            name = item["name"]
            schema = item.get("schema")
            try:
                if kind == "schema":
                    cursor.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
                elif kind == "view":
                    cursor.execute(
                        f"DROP VIEW IF EXISTS {schema}.{name} CASCADE"
                    )
                elif kind == "table":
                    cursor.execute(
                        f"DROP TABLE IF EXISTS {schema}.{name} CASCADE"
                    )
            except Exception:  # noqa: S110, BLE001
                pass
    conn.close()


@pytest.fixture
def scenario_context() -> Generator[dict[str, Any], None, None]:
    """Shared mutable dict for passing state between BDD steps.

    Cleanup runs after the test via ``yield`` fixture teardown.
    """
    ctx: dict[str, Any] = {"cleanup": []}
    yield ctx
    _run_cleanup(ctx)
