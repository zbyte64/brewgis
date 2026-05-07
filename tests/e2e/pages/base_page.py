"""Base Page Object with common helpers for e2e tests."""
from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BasePage:
    """Shared page object methods for all pages."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def dump_state(self, label: str = "") -> str:
        """Return human-readable page state for debugging."""
        lines = []
        with suppress(Exception):
            lines.append(f"URL: {self.page.url}")
            lines.append(f"Title: {self.page.title()}")
        with suppress(Exception):
            snapshot = self.page.accessibility.snapshot()
            if snapshot:
                visible = []

                def _collect(node, depth=0) -> None:
                    role = node.get("role", "?")
                    name = node.get("name", "")
                    if role not in ("none", "generic", "InlineTextBox"):
                        visible.append(f"  {'  ' * depth}[{role}] {name}"[:160])
                    for c in node.get("children", []):
                        _collect(c, depth + 1)

                _collect(snapshot)
                lines.append(f"--- Visible elements ({len(visible)}) ---")
                lines.extend(visible[:60])
        state = "\n".join(lines)
        if label:
            state = f"=== {label} ===\n" + state
        return state

    def fill(self, selector: str, value: str) -> None:
        """Fill a field; on timeout, dump page state."""
        try:
            self.page.fill(selector, value, timeout=10000)
        except Exception as e:
            state = self.dump_state(f"fill('{selector}', '{value}') failed")
            msg = f"{e}\n\nPage state:\n{state}"
            raise type(e)(msg) from e

    def click(self, selector: str) -> None:
        """Click a locator; on timeout, dump page state."""
        try:
            self.page.click(selector, timeout=10000)
        except Exception as e:
            state = self.dump_state(f"click('{selector}') failed")
            msg = f"{e}\n\nPage state:\n{state}"
            raise type(e)(msg) from e

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
