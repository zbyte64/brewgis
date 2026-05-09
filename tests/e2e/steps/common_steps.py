"""Shared step definitions reused across features."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.pages.auth_page import AuthPage
from tests.e2e.pages.base_page import BasePage
from tests.factories import BuildingTypeFactory
from tests.factories import LayerFactory
from tests.factories import PlaceTypeFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.sync_api import Page


# ── Given steps ────────────────────────────────────────────────────────


@given("the user is logged in")
def user_logged_in(logged_in_page: Page) -> Page:
    """Ensure the user has a valid session."""
    return logged_in_page


@given("the user is not logged in")
def user_not_logged_in() -> None:
    """Ensure no user is logged in."""
    return


@given(parsers.parse("a workspace named {name} exists"))
def workspace_exists(name: str, db) -> WorkspaceFactory:  # type: ignore[no-untyped-def]
    """Create a workspace with the given name."""
    return WorkspaceFactory(name=name)


@given(parsers.parse('a layer named "{name}" exists in workspace "{ws_name}"'))
def layer_exists(name: str, ws_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a layer in the named workspace."""
    ws = WorkspaceFactory(name=ws_name)
    LayerFactory(name=name, workspace=ws)


@given(parsers.parse("a building type named {name} exists"))
def building_type_exists(name: str, db) -> BuildingTypeFactory:  # type: ignore[no-untyped-def]
    """Create a building type with the given name."""
    return BuildingTypeFactory(name=name)


@given(parsers.parse("a place type named {name} exists"))
def place_type_exists(name: str, db) -> PlaceTypeFactory:  # type: ignore[no-untyped-def]
    """Create a place type with the given name."""
    return PlaceTypeFactory(name=name)


# ── When steps ─────────────────────────────────────────────────────────


@when(parsers.parse('I navigate to "{url}"'))
def navigate(page: Page, live_server_url: str, url: str) -> None:
    """Navigate to the given URL path."""
    full_url = live_server_url + url
    page.goto(full_url, wait_until="networkidle")


@when(parsers.parse('I take a screenshot "{name}"'))
def take_screenshot(page: Page, screenshots_dir: Path, name: str) -> None:
    """Take a screenshot and save it."""
    dest = screenshots_dir / f"{name}.png"
    page.screenshot(path=str(dest))


# ── Then steps ─────────────────────────────────────────────────────────


@then(parsers.parse("the page title contains {text}"))
def page_title_contains(page: Page, text: str) -> None:
    """Check the page title contains the given text."""
    BasePage(page).assert_text_visible(text)


@then(parsers.parse('I should see "{text}"'))
def i_should_see(page: Page, text: str) -> None:
    """Assert the given text is visible on the page."""
    BasePage(page).assert_text_visible(text)


@then(parsers.parse('I should not see "{text}"'))
def i_should_not_see(page: Page, text: str) -> None:
    """Assert the given text is NOT visible."""
    BasePage(page).assert_text_not_visible(text)


@then("the response status is 200")
def response_status(page: Page) -> None:
    """Assert the page loaded successfully."""
    assert page.url, "Page URL should not be empty"
    assert page.title(), "Page title should not be empty"


@then(parsers.parse('I should see "{text}" in the navigation'))
def see_in_nav(page: Page, text: str) -> None:
    """Assert text appears in the navbar."""
    navbar = page.locator(".navbar")
    assert navbar.is_visible(), "Navbar should be visible"
    nav_text = navbar.text_content() or ""
    assert text in nav_text, f"Expected '{text}' in navbar, got '{nav_text}'"


@then(parsers.parse('I should see a "{text}" link'))
def see_link(page: Page, text: str) -> None:
    """Assert a link with the given text is visible."""
    link = page.get_by_role("link", name=text)
    assert link.is_visible(), f'Expected link "{text}" to be visible'


@then(parsers.parse("{text} in the page title"))
def title_contains_text(page: Page, text: str) -> None:
    """Check that the page title contains the given text."""
    title = page.title()
    assert text in title, f"Expected '{text}' in page title, got '{title}'"


@then("I should be on the login page")
def on_login_page(page: Page) -> None:
    """Check we're redirected to the login page."""
    assert "/accounts/login/" in page.url, f"Expected login page, got URL: {page.url}"


@then("I should be on the home page")
def on_home_page(page: Page, live_server_url: str) -> None:
    """Check we're on the home page."""
    url_prefix = live_server_url.rstrip("/") + "/"
    assert page.url.rstrip("/") == url_prefix.rstrip("/"), (
        f"Expected home page, got URL: {page.url}"
    )


@then("I should see an error message on the login page")
def login_error_message(page: Page) -> None:
    """Check that an error message is visible on the login page."""
    auth = AuthPage(page, "")
    error = auth.get_error_text()
    assert error is not None, "Expected error message on login page"
    assert len(error) > 0, "Error message should not be empty"


@then("I should see a validation error message")
def validation_error(page: Page) -> None:
    """Check that a validation error is visible somewhere on the page."""
    error_elements = page.locator(
        ".invalid-feedback, .alert-danger, .errorlist, .is-invalid"
    )
    assert error_elements.count() > 0, "Expected validation error to be visible"


@then("I should see a file upload field")
def file_upload_field(page: Page) -> None:
    """Check that a file input is visible."""
    file_input = page.locator("input[type=file]")
    assert file_input.is_visible(), "Expected file upload field to be visible"


@then("the map web component should be visible")
def map_component_visible(page: Page) -> None:
    """Check that the brew-gis-map web component is on the page."""
    component = page.locator("brew-gis-map")
    assert component.is_visible(), "Expected brew-gis-map component to be visible"


@then('I should see a "Back" button')
def back_button_visible(page: Page) -> None:
    """Check that a Back button/link is visible."""
    back = page.get_by_role("link", name="Back")
    assert back.is_visible(), 'Expected "Back" button to be visible'


@then("I should see a form with name and density fields")
def form_with_name_density(page: Page) -> None:
    """Check form contains name and density-related fields."""
    name_field = page.get_by_label("Name", exact=False)
    density_field = page.locator("#id_du_per_acre, [name=du_per_acre]")
    assert name_field.is_visible(), "Expected Name field"
    assert density_field.is_visible(), "Expected density field"


@then("I should see a form with name and ROW allocation fields")
def form_with_name_row(page: Page) -> None:
    """Check form contains name and ROW allocation fields."""
    name_field = page.get_by_label("Name", exact=False)
    row_field = page.locator("#id_row_allocation_pct, [name=row_allocation_pct]")
    assert name_field.is_visible(), "Expected Name field"
    assert row_field.is_visible(), "Expected ROW allocation field"
