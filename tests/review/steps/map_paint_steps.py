"""Step definitions for Map + Paint feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.map_page import MapReviewPage

scenarios(str(Path(__file__).parent.parent / "features" / "map_paint.feature"))


@when("I navigate to the map page")
def navigate_map_page(page, live_server_url) -> None:
    """Navigate to the map page for the most recently created workspace."""
    ws = Workspace.objects.last()
    assert ws is not None, "No workspace found in database"
    MapReviewPage(page).navigate_to_map(ws.pk, live_server_url)


@then("the map web component should be visible")
def map_component_visible(page) -> None:
    """Check the brew-gis-map component is visible."""
    assert MapReviewPage(page).map_component_is_visible(), (
        "Expected brew-gis-map component to be visible"
    )


@then(parsers.parse('I should see a "Back" button'))
def back_button_visible(page) -> None:
    """Check a Back link is visible."""
    assert MapReviewPage(page).has_back_button(), (
        'Expected a "Back" button to be visible'
    )


@then("I should see a scenario empty state")
def scenario_empty_state_visible(page) -> None:
    """Check the scenario empty state message is visible."""
    assert MapReviewPage(page).scenario_empty_state_visible(), (
        "Expected scenario empty state to be visible"
    )
