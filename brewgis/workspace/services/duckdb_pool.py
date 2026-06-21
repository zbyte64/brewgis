"""Thread-local read-only DuckDB connection pool for concurrent MCP access.

Each thread gets its own read-only connection — no locking needed between
concurrent MCP requests.  Write-mode operations (sqlmesh plan/run) use the
existing RLock-serialized SingletonConnectionPool from ``config.py``.
"""

from __future__ import annotations

import threading

import duckdb


class DuckDBReadOnlyPool:
    """Thread-local read-only DuckDB connections for concurrent access.

    Usage::

        pool = DuckDBReadOnlyPool("/app/planning/duckdb_cache.db")
        conn = pool.get_connection()
        conn.execute("SELECT 1")
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Return the current thread's read-only connection (lazy-created)."""
        if not hasattr(self._local, "conn"):
            self._local.conn = duckdb.connect(self._db_path, read_only=True)
        return self._local.conn
