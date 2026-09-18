"""Step definitions for place types feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.e2e.pages.building_types_page import PlaceTypesPage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "place_types.feature"))


@when("I navigate to the place types page")
def navigate_place_types(page: Page, live_server_url: str, db) -> None:  # type: ignore[no-untyped-def]
    """Navigate to the place types list page."""
    workspace = Workspace.objects.get(name="Place Types WS")
    PlaceTypesPage(page, live_server_url).navigate_to_list(workspace.pk)


@when(parsers.parse('I click "{text}"'))
def click_link(page: Page, text: str) -> None:
    """Click a link with the given text."""
    page.get_by_role("link", name=text).click()
