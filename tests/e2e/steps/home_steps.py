"""Step definitions for home page feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import when

from tests.e2e.pages.home_page import HomePage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "home.feature"))


@when("I navigate to the home page")
def navigate_home(page: Page, live_server_url: str) -> None:
    """Navigate to the home page."""
    HomePage(page, live_server_url).navigate_to()
