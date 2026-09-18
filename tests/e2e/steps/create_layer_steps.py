"""Step definitions for create layer feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import when

from tests.e2e.pages.base_page import BasePage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "create_layer.feature"))


@when("I navigate to the create layer page")
def navigate_create_layer(page: Page, live_server_url: str) -> None:
    """Navigate to the create layer page."""
    BasePage(page).navigate(live_server_url + "/layers/create/")


@when("I submit the form with empty fields")
def submit_empty_form(page: Page) -> None:
    """Submit the create layer form without filling it.

    Disables HTML5 constraint validation first — otherwise the browser
    blocks the empty submit client-side and the request never reaches the
    server, so the server-side validation errors this scenario checks for
    would never render.
    """
    page.evaluate("document.querySelector('form').noValidate = true")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
