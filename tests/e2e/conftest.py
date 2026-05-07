"""Playwright + Django live_server fixtures for e2e tests."""
from __future__ import annotations

import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.test import override_settings

from tests.e2e.pages.auth_page import AuthPage
from tests.factories import UserFactory

# Allow synchronous DB access from Playwright's async event loop
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# All e2e tests need database access (for live_server, factories, etc.)
pytestmark = pytest.mark.django_db
if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from playwright.sync_api import Browser
    from playwright.sync_api import ConsoleMessage
    from playwright.sync_api import Page
    from playwright.sync_api import Playwright
    from pytest_django.live_server_helper import LiveServer


# ── CLI options ────────────────────────────────────────────────────────

def pytest_addoption(parser) -> None:
    parser.addoption(
        "--e2e-debug",
        action="store_true",
        default=False,
        help="Run E2E tests in headed (visible) browser mode",
    )

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
def browser(playwright: Playwright, request) -> Browser:
    """Launch a Chromium browser for the session."""
    headless = not request.config.getoption("--e2e-debug", default=False)
    browser = playwright.chromium.launch(headless=headless, slow_mo=100 if not headless else 0)
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


@pytest.fixture(autouse=True)
def _capture_page_errors(page: Page, screenshots_dir: Path) -> None:
    """Capture console errors and dump page state on failure."""
    errors: list[str] = []

    def _log_error(msg: ConsoleMessage) -> None:
        errors.append(f"[{msg.type}] {msg.text}")

    page.on("console", _log_error)

    yield

    page.remove_listener("console", _log_error)

    # If test failed, dump diagnostics
    if hasattr(page, "_diagnostic_dump"):
        diag_path = screenshots_dir / "diagnostics.txt"
        diag_path.write_text(page._diagnostic_dump)  # noqa: SLF001
        print(f"\n[DX] Diagnostics dumped to: {diag_path}", file=sys.stderr)  # noqa: T201
        print(f"[DX] Page URL: {page.url}", file=sys.stderr)  # noqa: T201
        if errors:
            print(f"[DX] Console errors: {len(errors)} captured", file=sys.stderr)  # noqa: T201
            for e in errors[-10:]:
                print(f"     {e}", file=sys.stderr)  # noqa: T201


@pytest.fixture
def logged_in_page(page: Page, live_server_url: str, logged_in_user: User) -> Page:
    """Return a page that is already logged in."""
    auth_page = AuthPage(page, live_server_url)
    auth_page.navigate_to_login()
    auth_page.login(logged_in_user.username, "testpass123")
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
    """Capture screenshot and DOM tree dump on test failure."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = item.funcargs.get("page") or item.funcargs.get("logged_in_page")
        if page:
            node_id = item.nodeid.replace("::", "/").replace("[", "/").replace("]", "")
            sd = Path("tests/e2e/screenshots") / node_id
            sd.mkdir(parents=True, exist_ok=True)

            # Screenshot
            screenshot_path = sd / "failure.png"
            page.screenshot(path=str(screenshot_path))

            # DOM snapshot (visible elements via accessibility tree)
            with suppress(Exception):
                snapshot = page.accessibility.snapshot()
                if snapshot:
                    elements = []
                    def flatten(node: dict, depth: int = 0) -> None:
                        role = node.get("role", "?")
                        name = node.get("name", "")
                        if role not in ("none", "generic"):
                            elements.append("  " * depth + f"[{role}] {name}"[:200])
                        for c in node.get("children", []):
                            flatten(c, depth + 1)
                    flatten(snapshot)
                    dom_path = sd / "dom_tree.txt"
                    dom_path.write_text("\n".join(elements))

            # Print locations to stderr so they're visible in CI output
            print(f"\n=== E2E FAILURE DIAGNOSTICS [{item.nodeid}] ===", file=sys.stderr)  # noqa: T201
            print(f"   Screenshot: {screenshot_path}", file=sys.stderr)  # noqa: T201
            print(f"   DOM tree:   {sd / 'dom_tree.txt'}", file=sys.stderr)  # noqa: T201
            print("===========================================\n", file=sys.stderr)  # noqa: T201

