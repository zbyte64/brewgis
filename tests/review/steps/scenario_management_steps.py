"""Step definitions for Scenario Management feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(
    str(Path(__file__).parent.parent / "features" / "scenario_management.feature")
)


@when("I navigate to the create scenario page for that workspace")
def navigate_to_create_scenario(page: Page, live_server_url: str) -> None:
    """Navigate to the create scenario page for the most recent workspace."""
    from brewgis.workspace.models import Workspace

    ws = Workspace.objects.latest("pk")
    page.goto(f"{live_server_url}/{ws.pk}/scenario/create/", wait_until="networkidle")


@then("I should see the scenario form")
def scenario_form_visible(page: Page) -> None:
    """Check the scenario form is visible on the page."""
    form = page.locator("form")
    assert form.is_visible(), "Expected scenario form to be visible"
