"""Step definitions for workspace map feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import expect
from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Workspace
from tests.e2e.pages.base_page import BasePage
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.factories import LayerFactory

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "workspace_map.feature"))


@when(parsers.parse('I navigate to the map page for workspace "{ws_name}"'))
def navigate_map(page: Page, live_server_url: str, ws_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Navigate to the map page for the named workspace."""

    ws = Workspace.objects.get(name=ws_name)
    BasePage(page).navigate(live_server_url + f"/{ws.pk}/map/")


# ── Live updates over the map's event websocket ─────────────────────────

# Set on the page once it is open; a reload would wipe it.
_NO_RELOAD_MARKER = "window.__brewgisNoReload"


@given(parsers.parse('the workspace "{ws_name}" has a layer named "{name}"'))
def workspace_has_layer(ws_name: str, name: str, db) -> None:  # type: ignore[no-untyped-def]
    LayerFactory(workspace=Workspace.objects.get(name=ws_name), name=name)


@when("the map's live update connection is open")
def live_connection_open(page: Page) -> None:
    page.wait_for_function(
        "() => document.querySelector('brew-gis-map')?._socket?.isOpen === true"
    )
    page.evaluate(f"() => {{ {_NO_RELOAD_MARKER} = true }}")


@when(parsers.parse('another tab hides the layer "{name}"'))
def another_tab_hides_layer(  # type: ignore[no-untyped-def]
    context: BrowserContext, live_server_url: str, name: str, db
) -> None:
    """Toggle the layer's visibility from a second page, as its legend checkbox does."""
    layer = Layer.objects.get(name=name)
    other = context.new_page()
    BasePage(other).navigate(live_server_url + f"/{layer.workspace_id}/map/")
    status = other.evaluate(
        """async (url) => {
          const token = document.querySelector('meta[name="csrf-token"]').content
          const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': token } })
          return response.status
        }""",
        f"/layers/{layer.pk}/toggle-visibility/",
    )
    other.close()
    assert status == 204


@then(parsers.parse('the map shows the layer "{name}" as hidden without reloading'))
def map_shows_layer_hidden(page: Page, name: str) -> None:
    page.wait_for_function(
        """(name) => {
          const layer = document.querySelector('brew-gis-map').layers.find((l) => l.name === name)
          return layer?.layout?.visibility === 'none'
        }""",
        arg=name,
    )
    assert page.evaluate(f"() => {_NO_RELOAD_MARKER} === true")
    expect(page.locator("brew-gis-map")).to_be_visible()
