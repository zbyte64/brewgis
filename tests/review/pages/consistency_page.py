"""Page object for cross-surface consistency checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ConsistencyPage(BasePage):
    """Cross-surface UX consistency checks."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate(self, path: str) -> None:
        """Navigate to a given path."""
        self.page.goto(f"{self.base_url}{path}", wait_until="networkidle")

    def has_navbar(self) -> bool:
        """Check if the main navigation bar is present."""
        return self.page.locator("nav.navbar").is_visible()

    def navbar_links(self) -> list[str]:
        """Return visible navbar link labels."""
        nav = self.page.locator("nav.navbar")
        return [
            a.inner_text().strip()
            for a in nav.locator("a.nav-link, a.dropdown-item").all()
        ]
