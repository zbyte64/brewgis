"""Page object for the Basemap picker (UX inspection)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page  # noqa: F401


class BasemapsPage(BasePage):
    """UX inspection methods for the basemap picker."""

    def navigate_to_picker(self, live_server_url: str) -> None:
        """Navigate to the basemap list page."""
        self.page.goto(
            f"{live_server_url}/basemaps/",
            wait_until="networkidle",
        )

    def has_basemap_options(self) -> bool:
        """Check that basemap option cards/items are visible."""
        cards = self.page.locator(".basemap-picker .card")
        return cards.count() > 0
