"""Step definitions for authentication feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.pages.auth_page import AuthPage
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.factories import UserFactory

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "auth.feature"))


@given(parsers.parse('a user "{username}" exists'))
def user_exists(username: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a user with a verified email, matching the password login steps expect."""
    from allauth.account.models import EmailAddress

    user = UserFactory(username=username)
    EmailAddress.objects.create(
        user=user, email=user.email, verified=True, primary=True
    )


@when("I navigate to the login page")
def navigate_login(page: Page, live_server_url: str) -> None:
    """Navigate to the login page."""
    AuthPage(page, live_server_url).navigate_to_login()


@when(parsers.parse('I log in as "{username}" with password "{password}"'))
def login_action(
    page: Page, live_server_url: str, username: str, password: str
) -> None:
    """Fill login form and submit."""
    auth = AuthPage(page, live_server_url)
    auth.login(username, password)


@when("I log out")
def logout_action(page: Page, live_server_url: str) -> None:
    """Click Sign Out in the navbar."""
    AuthPage(page, live_server_url).logout()


@then("I should be on the home page")
def home_page(page: Page, live_server_url: str) -> None:
    """Verify we're on the home page after login."""
    url = page.url.rstrip("/")
    home_url = live_server_url.rstrip("/") + "/"
    assert url == home_url.rstrip("/") or url == home_url, (
        f"Expected home page, got {url}"
    )
