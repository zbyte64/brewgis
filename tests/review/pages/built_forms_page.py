"""Page object for Built Forms pages (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class BuiltFormsPage(BasePage):
    """UX inspection methods for Built Forms (Building Types, Place Types, Mix)."""

    def navigate_to_building_types(self, live_server_url: str) -> None:
        """Navigate to the building types list page."""
        self.navigate(f"{live_server_url}/workspace/building-types/")

    def navigate_to_place_types(self, live_server_url: str) -> None:
        """Navigate to the place types list page."""
        self.navigate(f"{live_server_url}/workspace/place-types/")

    def card_count(self) -> int:
        """Return the number of building type or place type cards visible."""
        return self.page.locator("div.row.row-cols-1 > div.col .card").count()

    def card_titles(self) -> list[str]:
        """Return the titles of all visible cards."""
        titles: list[str] = []
        for h5 in self.page.locator("div.card h5.card-title").all():
            titles.append(h5.inner_text().strip())
        for h6 in self.page.locator("div.card h6.card-title").all():
            titles.append(h6.inner_text().strip())
        return titles

    def has_create_button(self) -> bool:
        """Check if a create/add button is present."""
        return (
            self.page.get_by_role("link", name="Create").is_visible()
            or self.page.get_by_role("link", name="Add").is_visible()
            or self.page.get_by_role("link", name="New").is_visible()
        )

    def has_empty_message(self) -> bool:
        """Check if the page shows 'No building types' or 'No place types'."""
        return (
            self.page.locator("text=No building types").is_visible()
            or self.page.locator("text=No place types").is_visible()
        )

    def navigate_to_bake(self, live_server_url: str) -> None:
        """Navigate to the bake/apply page."""
        self.navigate(f"{live_server_url}/workspace/building-types/bake/")

    def has_bake_button(self) -> bool:
        """Check if a bake/apply button is accessible."""
        return self.page.get_by_role("button", name="Bake").is_visible()
