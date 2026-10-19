"""Page object for the workspace map page (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class MapReviewPage(BasePage):
    """UX inspection methods for the workspace map page."""

    def map_component_is_visible(self) -> bool:
        """Check the brew-gis-map web component is rendered."""
        return self.page.locator("brew-gis-map").is_visible()

    def scenario_empty_state_visible(self) -> bool:
        """Check if the scenario empty state message is visible."""
        return self.page.locator("text=No scenarios yet").is_visible()

    def navigate_to_map(self, workspace_pk: int, live_server_url: str) -> None:
        """Navigate to the map page for the given workspace."""
        self.navigate(f"{live_server_url}/{workspace_pk}/map/")

    def has_back_button(self) -> bool:
        """Check if a back navigation link is visible."""
        return self.page.get_by_role("link", name="Back").is_visible()
