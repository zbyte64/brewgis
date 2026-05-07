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
        """Fill in login form and submit.  Handles django-allauth's default form."""
        # Wait for the form to actually be attached to DOM
        try:
            self.page.wait_for_selector("form", state="attached", timeout=5000)
        except Exception:  # noqa: BLE001
            msg = f"Login form never appeared on page.\n{self.dump_state('no login form')}"
            raise AssertionError(msg) from None

        # Try multiple selector strategies for username/password
        selectors = {
            "login": ["input[name=login]", "#id_login", "input[autocomplete=username]"],
            "password": ["input[name=password]", "#id_password", "input[autocomplete=current-password]"],
        }

        for field, candidates in selectors.items():
            found = False
            for sel in candidates:
                if self.page.locator(sel).count() > 0:
                    self.page.fill(sel, (field == "login" and username) or password)
                    found = True
                    break
            if not found:
                msg = f"Could not find {field} field on login page.\n{self.dump_state(f'no {field} field')}"
                raise AssertionError(msg)

        # Submit button — try button type or role-based
        submit = self.page.locator("button[type=submit]")
        if submit.count() == 0:
            submit = self.page.get_by_role("button", name="Sign In")
        if submit.count() == 0:
            msg = f"Could not find submit button.\n{self.dump_state('no submit button')}"
            raise AssertionError(msg)
        submit.click()

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
