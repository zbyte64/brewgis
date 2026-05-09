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

    def breadcrumb_is_visible(self) -> bool:
        """Check if breadcrumb navigation is present on the current page."""
        return self.page.locator("nav[aria-label='breadcrumb']").is_visible()

    def breadcrumb_items(self) -> list[str]:
        """Return breadcrumb text items."""
        items = self.page.locator("nav[aria-label='breadcrumb'] ol li")
        return [it.inner_text().strip() for it in items.all()]

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

    def has_empty_state_message(self, page_text: str) -> bool:
        """Check if the page shows an empty state message."""
        return self.page.locator(f"text={page_text}").is_visible()
