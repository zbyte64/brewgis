"""Page object for the home page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class HomePage(BasePage):
    """Page object for the workspace home page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to(self) -> None:
        """Navigate to the home page."""
        self.navigate(self.base_url + "/")

    def has_workspace_named(self, name: str) -> bool:
        """Check if a workspace with the given name is listed."""
        return self.page.get_by_text(name, exact=True).is_visible()

    def get_workspace_count(self) -> int:
        """Count workspaces listed on the page."""
        return len(self.page.locator(".list-group-item").all())

    def click_view_map(self) -> None:
        """Click View Map for the first workspace."""
        self.page.get_by_role("link", name="View Map").first.click()

    def click_upload_gis_file(self) -> None:
        """Click the Upload GIS File link."""
        self.click_link("Upload GIS File")

    def click_create_layer(self) -> None:
        """Click the Create Layer link."""
        self.click_link("Create Layer")

    def click_building_types(self) -> None:
        """Click the Building Types link."""
        self.click_link("Building Types")

    def click_place_types(self) -> None:
        """Click the Place Types link."""
        self.click_link("Place Types")
