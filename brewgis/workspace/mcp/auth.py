"""Auth stub — Phase 5 will implement real authentication."""

import logging

logger = logging.getLogger(__name__)


def resolve_user(token: str | None = None) -> None:
    """Resolve user from MCP auth token.

    Currently returns None (no auth). Phase 5 will implement
    real token-to-user resolution.
    """
    return
