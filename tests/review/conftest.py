"""Pytest configuration for UX design review tests.

Review tests reuse existing e2e fixture infrastructure (Playwright browser,
logged-in page, factories) and are marked with @pytest.mark.review for
selective execution.

Fixtures are defined here rather than relying on pytest_plugins (which is
restricted to top-level conftests in pytest 8.1+) to avoid affecting the
rest of the test suite when review tests are discovered alongside other tests.

Many fixture implementations delegate to functions imported from
tests/e2e/conftest.py to avoid duplication.
"""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.test import override_settings

# Allow synchronous DB access from Playwright's async event loop
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# Review tests need database access (for live_server, factories, etc.)
pytestmark = pytest.mark.django_db

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from playwright.sync_api import Browser
    from playwright.sync_api import ConsoleMessage
    from playwright.sync_api import Page
    from playwright.sync_api import Playwright
    from pytest_django.live_server_helper import LiveServer


# ── Override ALLOWED_HOSTS for Playwright ────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _allowed_hosts() -> None:
    with override_settings(ALLOWED_HOSTS=["*"]):
        yield


# ── Playwright session fixtures ──────────────────────────────────────────


@pytest.fixture(scope="session")
def playwright() -> Playwright:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright, request) -> Browser:
    headless = not request.config.getoption("--e2e-debug", default=False)
    browser = playwright.chromium.launch(
        headless=headless,
        slow_mo=100 if not headless else 0,
        args=["--disable-dev-shm-usage"],
    )
    yield browser
    browser.close()


# ── Per-test browser context ─────────────────────────────────────────────


@pytest.fixture
def context(browser: Browser) -> None:
    context = browser.new_context(ignore_https_errors=True)
    yield context
    context.close()


@pytest.fixture
def page(context) -> Page:
    page = context.new_page()
    yield page
    page.close()


# ── Live server ──────────────────────────────────────────────────────────


@pytest.fixture
def live_server_url(live_server: LiveServer) -> str:
    return live_server.url


# ── Auth ─────────────────────────────────────────────────────────────────


@pytest.fixture
def logged_in_user(db) -> User:
    from tests.factories import UserFactory  # noqa: PLC0415

    return UserFactory()


@pytest.fixture
def logged_in_page(page: Page, live_server_url: str, logged_in_user: User) -> Page:
    from tests.e2e.pages.auth_page import AuthPage  # noqa: PLC0415

    auth_page = AuthPage(page, live_server_url)
    auth_page.navigate_to_login()
    auth_page.login(logged_in_user.username, "testpass123")
    page.wait_for_url(live_server_url + "/")
    return page


# ── Screenshots ──────────────────────────────────────────────────────────


@pytest.fixture
def screenshots_dir(request) -> Path:
    """Review tests get their own screenshots directory."""
    node_id = request.node.nodeid.replace("::", "/").replace("[", "/").replace("]", "")
    path = Path("tests/review/screenshots") / node_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def screenshot(page: Page, screenshots_dir: Path) -> None:
    _captured: list[Path] = []

    def _take(name: str) -> str:
        dest = screenshots_dir / f"{name}.png"
        page.screenshot(path=str(dest))
        _captured.append(dest)
        return str(dest)

    return _take


# ── Error capture ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _capture_page_errors(page: Page, screenshots_dir: Path) -> None:
    errors: list[str] = []

    def _log_error(msg: ConsoleMessage) -> None:
        errors.append(f"[{msg.type}] {msg.text}")

    page.on("console", _log_error)
    yield
    page.remove_listener("console", _log_error)

    if hasattr(page, "_diagnostic_dump"):
        diag_path = screenshots_dir / "diagnostics.txt"
        diag_path.write_text(page._diagnostic_dump)  # noqa: SLF001
        print(f"\n[DX] Diagnostics dumped to: {diag_path}", file=sys.stderr)  # noqa: T201
        print(f"[DX] Page URL: {page.url}", file=sys.stderr)  # noqa: T201
        if errors:
            print(f"[DX] Console errors: {len(errors)} captured", file=sys.stderr)  # noqa: T201
            for e in errors[-10:]:
                print(f"     {e}", file=sys.stderr)  # noqa: T201


# ── CLI options ──────────────────────────────────────────────────────────


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--e2e-debug",
        action="store_true",
        default=False,
        help="Run E2E tests in headed (visible) browser mode",
    )


# ── Failure screenshot / DOM dump ────────────────────────────────────────


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call) -> None:
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        page = item.funcargs.get("page") or item.funcargs.get("logged_in_page")
        if page:
            node_id = item.nodeid.replace("::", "/").replace("[", "/").replace("]", "")
            sd = Path("tests/review/screenshots") / node_id
            sd.mkdir(parents=True, exist_ok=True)

            # Screenshot
            screenshot_path = sd / "failure.png"
            page.screenshot(path=str(screenshot_path))

            # DOM snapshot
            with suppress(Exception):
                snapshot = page.accessibility.snapshot()
                if snapshot:
                    elements: list[str] = []

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

            print(f"\n=== REVIEW FAILURE DIAGNOSTICS [{item.nodeid}] ===", file=sys.stderr)  # noqa: T201
            print(f"   Screenshot: {screenshot_path}", file=sys.stderr)  # noqa: T201
            print(f"   DOM tree:   {sd / 'dom_tree.txt'}", file=sys.stderr)  # noqa: T201
            print("===========================================\n", file=sys.stderr)  # noqa: T201
