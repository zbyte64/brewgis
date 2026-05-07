"""Playwright + Django live_server fixtures for e2e tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.test import override_settings

from tests.factories import UserFactory

# Allow synchronous DB access from Playwright's async event loop
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# All e2e tests need database access (for live_server, factories, etc.)
pytestmark = pytest.mark.django_db
if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from playwright.sync_api import Browser
    from playwright.sync_api import Page
    from playwright.sync_api import Playwright
    from pytest_django.live_server_helper import LiveServer


# Override ALLOWED_HOSTS so Playwright can connect via Docker network
@pytest.fixture(scope="session", autouse=True)
def _allowed_hosts() -> None:
    with override_settings(ALLOWED_HOSTS=["*"]):
        yield


@pytest.fixture(scope="session")
def playwright() -> Playwright:
    """Create a Playwright instance for the session."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Browser:
    """Launch a Chromium browser for the session."""
    browser = playwright.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture
def context(browser: Browser) -> None:
    """Fresh browser context per test — isolated cookies and storage."""
    context = browser.new_context(ignore_https_errors=True)
    yield context
    context.close()


@pytest.fixture
def page(context) -> Page:
    """Fresh page per test."""
    page = context.new_page()
    yield page
    page.close()


@pytest.fixture
def live_server_url(live_server: LiveServer) -> str:
    """Return the live server URL for the test function."""
    return live_server.url


@pytest.fixture
def logged_in_user(db) -> User:
    """Create and return an authenticated user.

    Passwords are set with MD5 hasher in test settings for speed.
    """
    return UserFactory()


@pytest.fixture
def logged_in_page(page: Page, live_server_url: str, logged_in_user: User) -> Page:
    """Return a page that is already logged in."""
    page.goto(live_server_url + "/accounts/login/")
    page.fill("input[name=login]", logged_in_user.username)
    page.fill("input[name=password]", "testpass123")
    page.click("button[type=submit]")
    page.wait_for_url(live_server_url + "/")
    return page


@pytest.fixture
def screenshots_dir(request) -> Path:
    """Return the directory path for screenshots for the current test."""
    node_id = request.node.nodeid.replace("::", "/").replace("[", "/").replace("]", "")
    path = Path("tests/e2e/screenshots") / node_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def screenshot(page: Page, screenshots_dir: Path) -> None:
    """Take a screenshot with the given name."""
    _captured = []

    def _take(name: str) -> str:
        dest = screenshots_dir / f"{name}.png"
        page.screenshot(path=str(dest))
        _captured.append(dest)
        return str(dest)

    return _take


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call) -> None:
    """Capture screenshot on test failure."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = item.funcargs.get("page") or item.funcargs.get("logged_in_page")
        if page:
            node_id = item.nodeid.replace("::", "/").replace("[", "/").replace("]", "")
            screenshot_dir = Path("tests/e2e/screenshots") / node_id
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_dir / "failure.png"))
