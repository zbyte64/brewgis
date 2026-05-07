"""Step definitions for place types feature."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import when

from tests.e2e.pages.building_types_page import PlaceTypesPage


from pathlib import Path
from tests.e2e.steps.common_steps import *  # noqa: F403, F401

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "place_types.feature"))


@when("I navigate to the place types page")
def navigate_place_types(page: Page, live_server_url: str) -> None:
    """Navigate to the place types list page."""
    PlaceTypesPage(page, live_server_url).navigate_to_list()


@when(parsers.parse('I click "{text}"'))
def click_link(page: Page, text: str) -> None:
    """Click a link with the given text."""
    page.get_by_role("link", name=text).click()
