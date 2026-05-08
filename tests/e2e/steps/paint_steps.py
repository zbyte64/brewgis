"""Step definitions for paint mode feature (focused on UI interaction)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.test import override_settings
from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from tests.e2e.pages.base_page import BasePage
from tests.e2e.pages.map_page import MapPage
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from collections.abc import Generator

    from django.contrib.auth.models import User
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "paint.feature"))

# ── Module-level config ─────────────────────────────────────────────────

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.e2e,
]


# Disable mandatory email verification so login doesn't redirect to confirm-email.
@pytest.fixture(autouse=True)
def _disable_email_verification() -> Generator[None, None, None]:
    with override_settings(ACCOUNT_EMAIL_VERIFICATION="optional"):
        yield


# Override the conftest fixture with a more robust login flow.
@pytest.fixture
def logged_in_page(page: Page, live_server_url: str, logged_in_user: User) -> Page:
    """Login and wait for success, with fallback for confirm-email redirect."""
    from tests.e2e.pages.auth_page import AuthPage  # noqa: PLC0415

    auth_page = AuthPage(page, live_server_url)
    auth_page.navigate_to_login()
    auth_page.login(logged_in_user.username, "testpass123")
    page.wait_for_load_state("networkidle", timeout=30000)
    # Fallback: if confirm-email page shown, go directly to home
    if "/accounts/confirm-email/" in page.url:
        page.goto(live_server_url + "/", wait_until="networkidle")
    return page


# ── Given steps ────────────────────────────────────────────────────────


@given(parsers.parse('a workspace "{ws_name}" with scenario "{scenario_name}" exists'))
def workspace_with_scenario(ws_name: str, scenario_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a workspace and a scenario."""
    ws = WorkspaceFactory(name=ws_name)
    ScenarioFactory(workspace=ws, name=scenario_name)


@given(parsers.parse('a workspace "{ws_name}" with scenarios "{names}"'))
def workspace_with_scenarios(ws_name: str, names: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a workspace with multiple scenarios (comma-separated)."""
    ws = WorkspaceFactory(name=ws_name)
    for name_p in names.split(" and "):
        clean_name = name_p.strip().strip('"')
        ScenarioFactory(workspace=ws, name=clean_name)


@given(
    parsers.parse(
        'I am on the map page with "{scenario_name}" and workspace "{ws_name}"'
    )
)
def on_map_with_scenario(
    page: Page,
    live_server_url: str,
    scenario_name: str,
    ws_name: str,
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Navigate to the map page with a specific scenario selected."""
    ws = Workspace.objects.get(name=ws_name)
    scenario = Scenario.objects.get(name=scenario_name, workspace=ws)
    map_page = MapPage(page, live_server_url)
    map_page.navigate_to(ws.pk, scenario.pk)
    map_page.page.wait_for_load_state("networkidle")


@given("paint mode is active")
def paint_mode_active(page: Page, live_server_url: str) -> None:  # type: ignore[no-untyped-def]
    """Ensure paint mode is toggled on."""
    map_page = MapPage(page, live_server_url)
    map_page.click_paint_mode()
    map_page.page.wait_for_timeout(300)


@when(parsers.parse("I select {count} parcels"))
def select_parcels(page: Page, live_server_url: str, count: int) -> None:  # type: ignore[no-untyped-def]
    """Simulate selecting parcels on the map via JS event dispatch."""
    map_page = MapPage(page, live_server_url)
    count_int = int(count)
    fids = [str(i) for i in range(1, count_int + 1)]
    map_page.set_selected_features(fids)


# ── When steps ─────────────────────────────────────────────────────────


@given(parsers.parse('I select "{scenario_name}" from the scenario dropdown'))
@when(parsers.parse('I select "{scenario_name}" from the scenario dropdown'))
@then(parsers.parse('I select "{scenario_name}" from the scenario dropdown'))
def select_scenario(
    page: Page,
    live_server_url: str,
    scenario_name: str,
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Select a scenario from the dropdown by its name."""

    match = re.search(r"/(\d+)/map/", page.url)
    assert match, f"Could not find workspace pk in URL: {page.url}"
    ws = Workspace.objects.get(pk=int(match.group(1)))
    scenario = Scenario.objects.get(name=scenario_name, workspace=ws)
    map_page = MapPage(page, live_server_url)
    map_page.select_scenario_by_value(scenario.pk)
    map_page.page.wait_for_url("**/map/?scenario=**", timeout=10000)


@when(parsers.parse('I click "{button_text}"'))
def click_button(page: Page, live_server_url: str, button_text: str) -> None:
    """Click a button by its visible text."""
    map_page = MapPage(page, live_server_url)
    map_page.click_button(button_text)


@when(parsers.parse('I click "{button_text}" again'))
def click_paint_mode_again(page: Page, live_server_url: str, button_text: str) -> None:
    """Click the Paint Mode toggle a second time."""
    map_page = MapPage(page, live_server_url)
    map_page.click_paint_mode()
    map_page.page.wait_for_timeout(300)


@when("I clear the selection")
def clear_selection(page: Page, live_server_url: str) -> None:
    """Simulate clearing the parcel selection."""
    map_page = MapPage(page, live_server_url)
    map_page.set_selected_features([])


# ── Then steps ─────────────────────────────────────────────────────────


@then("the scenario should be active")
def scenario_active(page: Page) -> None:
    """Check that a scenario is selected and map has scenario-id set."""
    map_component = page.locator("brew-gis-map")
    scenario_id = map_component.get_attribute("scenario-id")
    assert scenario_id is not None, "Expected scenario-id on map component"
    assert scenario_id.isdigit(), f"Expected numeric scenario-id, got '{scenario_id}'"


@then("the Paint Mode button should be visible")
def paint_mode_button_visible(page: Page) -> None:
    """Check the Paint Mode toggle is visible."""
    btn = page.locator("#toggle-paint-btn")
    assert btn.is_visible(), "Paint Mode button should be visible"


@then("the paint toolbar should be visible")
def paint_toolbar_visible(page: Page) -> None:
    """Check the paint toolbar is visible."""
    toolbar = page.locator("#paint-toolbar")
    assert toolbar.is_visible(), "Paint toolbar should be visible"


@then("the paint toolbar should be hidden")
def paint_toolbar_hidden(page: Page) -> None:
    """Check the paint toolbar is hidden."""
    toolbar = page.locator("#paint-toolbar")
    assert not toolbar.is_visible(), "Paint toolbar should be hidden"


@then("the Apply button should be disabled")
def apply_disabled(page: Page) -> None:
    """Check Apply button is disabled."""
    btn = page.locator("#paint-apply-btn")
    assert btn.is_disabled(), "Apply button should be disabled"


@then("the Apply button should be enabled")
def apply_enabled(page: Page) -> None:
    """Check Apply button is enabled."""
    btn = page.locator("#paint-apply-btn")
    assert not btn.is_disabled(), "Apply button should be enabled"


@then("the Clear button should be disabled")
def clear_disabled(page: Page) -> None:
    """Check Clear button is disabled."""
    btn = page.locator("#paint-clear-btn")
    assert btn.is_disabled(), "Clear button should be disabled"


@then("the Clear button should be enabled")
def clear_enabled(page: Page) -> None:
    """Check Clear button is enabled."""
    btn = page.locator("#paint-clear-btn")
    assert not btn.is_disabled(), "Clear button should be enabled"


@then(parsers.parse('the feature count should show "{expected}"'))
def feature_count_matches(page: Page, expected: str) -> None:
    """Check the feature count display text."""
    count = page.locator("#paint-feature-count")
    assert count.is_visible(), "Feature count element should be visible"
    actual = count.text_content() or ""
    assert actual.strip() == expected, (
        f"Expected feature count '{expected}', got '{actual}'"
    )


@then(parsers.parse('the page URL should contain "{text}"'))
def url_contains(page: Page, text: str) -> None:
    """Check the URL contains the given substring."""
    assert text in page.url, f"Expected URL to contain '{text}', got '{page.url}'"


@when(parsers.parse('I navigate to the map page for workspace "{ws_name}"'))
def navigate_map(page: Page, live_server_url: str, ws_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Navigate to the map page for the named workspace."""
    ws = Workspace.objects.get(name=ws_name)
    BasePage(page).navigate(live_server_url + f"/{ws.pk}/map/")
