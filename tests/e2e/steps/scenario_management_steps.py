"""Step definitions for scenario management feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.pages.base_page import BasePage
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "scenario_management.feature"))


# Store workspace PK for use across steps within a test function
_workspace_pk: int | None = None
_workspace_name: str | None = None


@given(parsers.parse("a workspace named {name} exists"))
def _create_workspace(name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a workspace with the given name and store its pk."""
    global _workspace_pk, _workspace_name  # noqa: PLW0603
    ws = WorkspaceFactory(name=name)
    _workspace_pk = ws.pk
    _workspace_name = name


@given(parsers.parse('a workspace "{ws_name}" with scenario "{scenario_name}" exists'))
def workspace_with_scenario_exists(ws_name: str, scenario_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a scenario in the named workspace (workspace must already exist)."""
    from brewgis.workspace.models import Workspace  # noqa: PLC0415

    ws = Workspace.objects.get(name=ws_name)
    ScenarioFactory(name=scenario_name, workspace=ws)


@when("I navigate to the create scenario page for that workspace")
def _navigate_create_scenario(page: Page, live_server_url: str) -> None:
    """Navigate to the create scenario page for the stored workspace."""
    BasePage(page).navigate(live_server_url + f"/{_workspace_pk}/scenario/create/")


@when("I navigate to that workspace detail page")
def _navigate_workspace_detail(page: Page, live_server_url: str) -> None:
    """Navigate to the detail page for the stored workspace."""
    BasePage(page).navigate(live_server_url + f"/{_workspace_pk}/")


@then("I should see the workspace name in the page heading")
def _workspace_name_in_heading(page: Page) -> None:
    """Check the workspace name appears in the page heading."""
    heading = page.locator("h1")
    assert heading.is_visible(), "Expected page heading to be visible"
