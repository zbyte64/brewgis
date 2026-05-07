"""Base Page Object with common helpers for e2e tests."""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BasePage:
    """Shared page object methods for all pages."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def navigate(self, url: str) -> None:
        """Navigate to an absolute URL."""
        self.page.goto(url, wait_until="networkidle")

    def screenshot(self, name: str) -> str:
        """Take a screenshot and return the path."""
        path = f"tests/e2e/screenshots/{name}.png"
        self.page.screenshot(path=path)
        return path

    def get_title(self) -> str:
        """Return the page title."""
        return self.page.title()

    def assert_text_visible(self, text: str) -> None:
        """Assert the given text is visible on the page."""
        expect(self.page.get_by_text(text, exact=False)).to_be_visible()

    def assert_text_not_visible(self, text: str) -> None:
        """Assert the given text is NOT visible on the page."""
        expect(self.page.get_by_text(text, exact=False)).not_to_be_visible()

    def click_link(self, text: str) -> None:
        """Click a link by its visible text."""
        self.page.get_by_role("link", name=text).click()

    def click_button(self, text: str) -> None:
        """Click a button by its visible text."""
        self.page.get_by_role("button", name=text).click()

    def fill_input(self, label: str, value: str) -> None:
        """Fill an input field identified by its label text."""
        self.page.get_by_label(label).fill(value)
