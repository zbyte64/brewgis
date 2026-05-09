"""Step definitions for Basemap UX feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.basemaps_page import BasemapsPage

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "basemaps.feature"))


@given(parsers.parse('a basemap named "{name}" exists'))
def _basemap_exists(name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a basemap with the given name."""
    from brewgis.workspace.models import Basemap  # noqa: PLC0415

    Basemap.objects.create(
        name=name,
        style_url=f"https://example.com/{name.lower()}/style.json",
    )


@when("I navigate to the basemap picker")
def _navigate_basemap_picker(page: Page, live_server_url: str) -> None:
    """Navigate to the basemap picker page."""
    BasemapsPage(page).navigate_to_picker(live_server_url)


@then("I should see available basemap options")
def _see_basemap_options(page: Page) -> None:
    """Check that basemap options are visible."""
    assert BasemapsPage(page).has_basemap_options(), (
        "Expected basemap options to be visible"
    )
