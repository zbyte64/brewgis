"""Management command — start the BrewGIS MCP server over stdio."""

from __future__ import annotations

import logging

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

    def handle(self, *args: object, **options: object) -> None:
        import os
        from brewgis.workspace.mcp.server import run_stdio

        auth_token = options.get("auth_token") or os.environ.get("MCP_AUTH_TOKEN")
        if auth_token:
            logger.info("MCP auth token configured (auth itself is Phase 5)")
        else:
            logger.warning("MCP_AUTH_TOKEN not set — running without authentication (dev mode only)")

        logger.info("Starting BrewGIS MCP server over stdio...")
        run_stdio()
