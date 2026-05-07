"""Page object for authentication pages."""
from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class AuthPage(BasePage):
    """Page object for login and logout pages."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to_login(self) -> None:
        """Navigate to the login page."""
        self.navigate(self.base_url + "/accounts/login/")

    def login(self, username: str, password: str) -> None:
        """Fill in login form and submit."""
        self.page.fill("input[name=login]", username)
        self.page.fill("input[name=password]", password)
        self.page.click("button[type=submit]")

    def is_on_login_page(self) -> bool:
        """Check if we're on the login page."""
        return "/accounts/login/" in self.page.url

    def get_error_text(self) -> str | None:
        """Get the error message text if present."""
        error = self.page.locator(".alert-error, .errorlist, .alert-danger")
        if error.is_visible():
            return error.text_content()
        return None

    def logout(self) -> None:
        """Click the Sign Out link in the navbar."""
        self.page.get_by_role("link", name="Sign Out").click()

    def is_logged_in(self) -> bool:
        """Check if the Sign Out link is visible in the navbar."""
        return self.page.get_by_role("link", name="Sign Out").is_visible()
