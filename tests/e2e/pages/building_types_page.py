"""Page object for building type and place type pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BuildingTypesPage(BasePage):
    """Page object for building type list and create pages."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to_list(self) -> None:
        """Navigate to the building types list page."""
        self.navigate(self.base_url + "/built-forms/building-types/")

    def navigate_to_create(self) -> None:
        """Navigate to the create building type page."""
        self.navigate(self.base_url + "/built-forms/building-types/create/")

    def click_new(self) -> None:
        """Click the '+ New Building Type' button."""
        self.click_link("+ New Building Type")

    def has_form_field(self, field_label: str) -> bool:
        """Check if a form field with the given label is visible."""
        return self.page.get_by_label(field_label, exact=False).is_visible()

    def is_on_create_page(self) -> bool:
        """Check if we're on the create building type page."""
        return "building-types/create" in self.page.url


class PlaceTypesPage(BasePage):
    """Page object for place type list and create pages."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to_list(self) -> None:
        """Navigate to the place types list page."""
        self.navigate(self.base_url + "/built-forms/place-types/")

    def navigate_to_create(self) -> None:
        """Navigate to the create place type page."""
        self.navigate(self.base_url + "/built-forms/place-types/create/")

    def click_new(self) -> None:
        """Click the '+ New Place Type' button."""
        self.click_link("+ New Place Type")

    def has_form_field(self, field_label: str) -> bool:
        """Check if a form field with the given label is visible."""
        return self.page.get_by_label(field_label, exact=False).is_visible()

    def is_on_create_page(self) -> bool:
        """Check if we're on the create place type page."""
        return "place-types/create" in self.page.url
