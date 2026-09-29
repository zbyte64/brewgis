"""Page object for the built-form library — the map shell's Built Forms panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BuiltFormsPanelPage(BasePage):
    """Page object for the Built Forms panel on the workspace map.

    The library has no page of its own any more: ``?panel=built-forms`` opens
    the map with that sidebar tab already showing (see panel-manager.js), the
    panel lists both libraries, and its create/edit forms open in the map's
    right-hand drawer.
    """

    BODY = "#built-forms-body"
    BUILDING_ROWS = "#built-forms-body [data-building-type-pk]"
    PLACE_ROWS = "#built-forms-body [data-place-type-pk]"

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to_panel(self, workspace_pk: int) -> None:
        """Open the map with the Built Forms panel showing."""
        self.navigate(self.base_url + f"/{workspace_pk}/map/?panel=built-forms")
        # An anonymous visit is redirected to the login page instead of
        # rendering the shell, so the panel is only waited for when one is
        # going to appear — the auth scenario asserts that redirect itself.
        if "/accounts/login/" in self.page.url:
            return
        self.page.locator(self.BODY).wait_for(state="visible", timeout=15000)


class BuildingTypesPage(BuiltFormsPanelPage):
    """Page object for the panel's building-type list and its drawer form."""

    def click_new(self) -> None:
        """Click the panel's "+ New" action for building types."""
        self.page.click("#new-building-type-btn")
        self.page.locator("#right-panel-content #form-content").wait_for(
            state="visible", timeout=15000
        )

    def has_form_field(self, field_label: str) -> bool:
        """Check if a form field with the given label is visible."""
        return self.page.get_by_label(field_label, exact=False).is_visible()

    def row_names(self) -> list[str]:
        """Names of the building types listed in the panel."""
        return [
            el.inner_text().strip()
            for el in self.page.locator(
                f"{self.BUILDING_ROWS} button:first-child"
            ).all()
        ]


class PlaceTypesPage(BuiltFormsPanelPage):
    """Page object for the panel's place-type list and its drawer form."""

    def click_new(self) -> None:
        """Click the panel's "+ New" action for place types."""
        self.page.click("#new-place-type-btn")
        self.page.locator("#right-panel-content #form-content").wait_for(
            state="visible", timeout=15000
        )

    def has_form_field(self, field_label: str) -> bool:
        """Check if a form field with the given label is visible."""
        return self.page.get_by_label(field_label, exact=False).is_visible()

    def row_names(self) -> list[str]:
        """Names of the place types listed in the panel."""
        return [
            el.inner_text().strip()
            for el in self.page.locator(f"{self.PLACE_ROWS} button:first-child").all()
        ]
