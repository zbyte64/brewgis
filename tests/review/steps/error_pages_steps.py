"""Step definitions for Error Pages UX feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import scenarios
from pytest_bdd import when

from tests.e2e.steps.common_steps import *  # noqa: F403

scenarios(str(Path(__file__).parent.parent / "features" / "error_pages.feature"))


@when("I navigate to a non-existent page")
def navigate_nonexistent(page, live_server_url) -> None:
    """Navigate to a non-existent URL to trigger Django's 404 handler."""
    page.goto(live_server_url + "/nonexistent-page-xyz/", wait_until="networkidle")
