"""Step definitions for workspace creation feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.pages.workspace_creation_page import WorkspaceCreationPage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "workspace_creation.feature"))


@when("I navigate to the create workspace page")
def navigate_create_workspace(page: Page, live_server_url: str) -> None:
    """Navigate to the create workspace page."""
    WorkspaceCreationPage(page).navigate_to(live_server_url)


@then('I should see a "Name" form field')
def name_form_field(page: Page) -> None:
    """Assert the form has a Name input field."""
    from playwright.sync_api import expect

    expect(page.get_by_label("Name")).to_be_visible()
