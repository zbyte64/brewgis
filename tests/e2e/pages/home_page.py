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
