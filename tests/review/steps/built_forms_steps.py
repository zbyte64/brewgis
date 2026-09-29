"""Step definitions for the Built Forms feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.factories import BuildingTypeFactory
from tests.factories import PlaceTypeFactory
from tests.review.pages.built_forms_page import BuiltFormsPage

scenarios(str(Path(__file__).parent.parent / "features" / "built_forms.feature"))

_WORKSPACE_NAME = "Built Forms WS"


def _workspace() -> Workspace:
    """The workspace the review scenario's built forms live in.

    Building/place types are workspace-scoped and the panel is rendered on the
    workspace map, so the review's own fixtures have to share one workspace.
    The Background's ``a workspace named "Built Forms WS" exists`` creates it —
    and with it the BASE scenario the map page resolves — so every step here
    looks that workspace up by name rather than by "the newest row", which a
    factory-made built form (each of which would otherwise make its own
    scenario-less workspace) would shadow.
    """
    workspace = Workspace.objects.filter(name=_WORKSPACE_NAME).last()
    assert workspace is not None, f"No workspace named {_WORKSPACE_NAME!r} exists"
    return workspace


@given(
    parsers.parse('a building type named "{name}" exists in the built forms workspace')
)
def building_type_in_workspace(name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a building type in the workspace the panel is browsed in."""
    BuildingTypeFactory(workspace=_workspace(), name=name)


@given(parsers.parse('a place type named "{name}" exists in the built forms workspace'))
def place_type_in_workspace(name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a place type in the workspace the panel is browsed in."""
    PlaceTypeFactory(workspace=_workspace(), name=name)


@when("I navigate to the building types page")
def navigate_building_types(page, live_server_url) -> None:
    """Open the map with the Built Forms panel showing."""
    BuiltFormsPage(page).navigate_to_building_types(live_server_url, _workspace().pk)


@when("I navigate to the place types page")
def navigate_place_types(page, live_server_url) -> None:
    """Open the map with the Built Forms panel showing."""
    BuiltFormsPage(page).navigate_to_place_types(live_server_url, _workspace().pk)


@then("I should see built form rows")
def see_rows(page) -> None:
    """Check that library rows are visible."""
    count = BuiltFormsPage(page).row_count()
    assert count > 0, f"Expected built form rows, got count {count}"


@then(parsers.parse('I should see "{name}" in the rows'))
def see_row_title(page, name: str) -> None:
    """Check a specific name appears in the row titles."""
    titles = BuiltFormsPage(page).row_titles()
    assert name in titles, f"Expected '{name}' in built form rows, got {titles}"


@then("the panel should offer a new building type and a new place type")
def create_actions_accessible(page) -> None:
    """Check both create actions are present."""
    assert BuiltFormsPage(page).has_create_button(), (
        "Expected both + New actions to be accessible in the Built Forms panel"
    )


@then("each built form row should offer edit and delete actions")
def row_actions_accessible(page) -> None:
    """Check each row can open its form and delete itself."""
    assert BuiltFormsPage(page).every_row_has_actions(), (
        "Expected every built form row to offer edit and delete actions"
    )
