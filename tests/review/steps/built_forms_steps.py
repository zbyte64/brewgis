"""Step definitions for Built Forms feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.built_forms_page import BuiltFormsPage

scenarios(str(Path(__file__).parent.parent / "features" / "built_forms.feature"))


@when("I navigate to the building types page")
def navigate_building_types(page, live_server_url) -> None:
    """Navigate to the building types list."""
    BuiltFormsPage(page).navigate_to_building_types(live_server_url)


@when("I navigate to the place types page")
def navigate_place_types(page, live_server_url) -> None:
    """Navigate to the place types list."""
    BuiltFormsPage(page).navigate_to_place_types(live_server_url)


@then("I should see built form cards")
def see_cards(page) -> None:
    """Check that card elements are visible."""
    count = BuiltFormsPage(page).card_count()
    assert count > 0, f"Expected built form cards, got count {count}"


@then(parsers.parse('I should see "{name}" in the cards'))
def see_card_title(page, name: str) -> None:
    """Check a specific name appears in card titles."""
    titles = BuiltFormsPage(page).card_titles()
    assert name in titles, f"Expected '{name}' in card titles, got {titles}"


@then("a bake button should be accessible")
def bake_button_accessible(page) -> None:
    """Check the bake button is present."""
    assert BuiltFormsPage(page).has_bake_button(), (
        "Expected Bake button to be accessible"
    )
