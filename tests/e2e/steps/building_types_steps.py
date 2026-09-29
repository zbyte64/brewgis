"""Step definitions for the building types feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.e2e.pages.building_types_page import BuildingTypesPage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "building_types.feature"))


def _panel_page(page: Page, live_server_url: str) -> BuildingTypesPage:
    """The Built Forms panel, opened for the scenario's workspace."""
    return BuildingTypesPage(page, live_server_url)


@when("I navigate to the building types page")
def navigate_building_types(page: Page, live_server_url: str, db) -> None:  # type: ignore[no-untyped-def]
    """Open the map with the Built Forms panel showing."""
    workspace = Workspace.objects.get(name="Building Types WS")
    _panel_page(page, live_server_url).navigate_to_panel(workspace.pk)


@when("I click the new building type button")
def click_new_building_type(page: Page, live_server_url: str) -> None:
    """Open the building-type form in the map's drawer."""
    _panel_page(page, live_server_url).click_new()


@then("the built form panel should offer a new building type")
def new_building_type_button_visible(page: Page) -> None:
    """Check the panel's create action is present."""
    button = page.locator("#new-building-type-btn")
    assert button.is_visible(), "Expected a + New building type action in the panel"
