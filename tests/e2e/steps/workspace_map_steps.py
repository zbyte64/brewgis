"""Step definitions for workspace map feature."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.e2e.pages.base_page import BasePage


from pathlib import Path
from tests.e2e.steps.common_steps import *  # noqa: F403, F401

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "workspace_map.feature"))


@when(parsers.parse('I navigate to the map page for workspace "{ws_name}"'))
def navigate_map(page: Page, live_server_url: str, ws_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Navigate to the map page for the named workspace."""

    ws = Workspace.objects.get(name=ws_name)
    BasePage(page).navigate(live_server_url + f"/{ws.pk}/map/")
