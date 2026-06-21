"""Management command — start the BrewGIS MCP server over stdio."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

import duckdb
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Start the MCP server."""

    help = "Start the BrewGIS MCP server over stdio"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--auth-token",
            type=str,
            default=None,
            help="MCP auth token (overrides MCP_AUTH_TOKEN env var)",
        )
        parser.add_argument(
            "--transport",
            type=str,
            default="streamable-http",
            choices=["stdio", "sse", "streamable-http"],
            help="Transport protocol (default: streamable-http)",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host to bind for SSE transport (default: 0.0.0.0)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8002,
            help="Port to bind for SSE transport (default: 8002)",
        )
        parser.add_argument(
            "--wait",
            action="store_true",
            default=False,
            help="Wait for DuckDB lock to clear instead of exiting immediately (stdio only)",
        )
        parser.add_argument(
            "--wait-timeout",
            type=int,
            default=300,
            help="Max seconds to wait for DuckDB lock (only with --wait)",
        )

    def handle(self, *args: object, **options: object) -> None:
        # Allow sync Django ORM calls from FastMCP's async stdio context
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        transport: str = options.get("transport", "sse")
        auth_token: str | None = options.get("auth_token") or os.environ.get(
            "MCP_AUTH_TOKEN"
        )

        if transport == "sse":
            self._handle_sse(auth_token, options)
        elif transport == "streamable-http":
            self._handle_streamable_http(auth_token, options)
        else:
            self._handle_stdio(auth_token, options)

    def _handle_streamable_http(
        self,
        auth_token: str | None,
        options: dict[str, object],
    ) -> None:
        """Start the MCP server with Streamable HTTP transport.

        Sets ``SQLMESH_DUCKDB_READONLY=1`` before importing any SQLMesh
        modules so that ``SingletonConnectionPool`` uses thread-local
        read-only DuckDB connections.
        """
        os.environ["SQLMESH_DUCKDB_READONLY"] = "1"

        from brewgis.workspace.mcp.server import run_streamable_http

        if auth_token:
            logger.info("MCP auth token configured (auth itself is Phase 5)")
        else:
            logger.warning(
                "MCP_AUTH_TOKEN not set — running without authentication (dev mode only)"
            )

        host: str = str(options.get("host", "0.0.0.0"))
        port: int = int(options.get("port", 8002))

        logger.info(
            "Starting BrewGIS MCP server over Streamable HTTP on %s:%d...",
            host,
            port,
        )
        run_streamable_http(host=host, port=port)

    def _handle_sse(
        self,
        auth_token: str | None,
        options: dict[str, object],
    ) -> None:
        """Start the MCP server with SSE transport (long-lived HTTP).

        Sets ``SQLMESH_DUCKDB_READONLY=1`` before importing any SQLMesh
        modules so that ``SingletonConnectionPool`` uses thread-local
        read-only DuckDB connections.
        """
        os.environ["SQLMESH_DUCKDB_READONLY"] = "1"

        from brewgis.workspace.mcp.server import run_sse

        if auth_token:
            logger.info("MCP auth token configured (auth itself is Phase 5)")
        else:
            logger.warning(
                "MCP_AUTH_TOKEN not set — running without authentication (dev mode only)"
            )

        host: str = str(options.get("host", "0.0.0.0"))
        port: int = int(options.get("port", 8002))

        logger.info("Starting BrewGIS MCP server over SSE on %s:%d...", host, port)
        run_sse(host=host, port=port)

    def _handle_stdio(
        self,
        auth_token: str | None,
        options: dict[str, object],
    ) -> None:
        """Start the MCP server with stdio transport (backward compat)."""
        # Pre-flight: check DuckDB availability before expensive SQLMesh init
        db_path = "/app/planning/duckdb_cache.db"
        if not self._check_duckdb_available(db_path, timeout=2.0):
            if options.get("wait"):
                timeout = options.get("wait_timeout", 300)
                if not self._wait_for_duckdb(db_path, timeout):
                    self.stderr.write(
                        f"run_mcp: Timed out waiting for DuckDB lock after {timeout}s.\n"
                        f"  Path: {db_path}\n"
                    )
                    sys.exit(1)
            else:
                self.stderr.write(
                    "run_mcp: DuckDB is locked by another process.\n"
                    f"  Path: {db_path}\n"
                    "  Use --wait to retry with a timeout "
                    "(e.g. --wait --wait-timeout 60).\n"
                )
                sys.exit(1)

        from brewgis.workspace.mcp.server import run_stdio

        if auth_token:
            logger.info("MCP auth token configured (auth itself is Phase 5)")
        else:
            logger.warning(
                "MCP_AUTH_TOKEN not set — running without authentication (dev mode only)"
            )

        logger.info("Starting BrewGIS MCP server over stdio...")
        run_stdio()

    @staticmethod
    def _check_duckdb_available(db_path: str, timeout: float = 2.0) -> bool:
        """Try to open DuckDB as read-only within *timeout* seconds."""
        result: dict = {}

        def _try() -> None:
            try:
                con = duckdb.connect(db_path, read_only=True)
                con.close()
                result["ok"] = True
            except (duckdb.Error, OSError) as e:
                result["error"] = str(e)

        t = threading.Thread(target=_try, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return result.get("ok", False)

    @staticmethod
    def _wait_for_duckdb(db_path: str, timeout: int, poll: float = 2.0) -> bool:
        """Poll DuckDB availability until timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if Command._check_duckdb_available(db_path, timeout=poll):
                return True
            time.sleep(poll)
        return False
