"""Conftest for review step definitions — imports shared steps to register them.

Each feature file under tests/review/features/ has a corresponding step module
under tests/review/steps/. Step modules declare their scenarios() binding and
implement review-specific Given/When/Then functions.

Shared e2e BDD steps (e.g., "Given the user is logged in") are imported by the
parent tests/review/conftest.py. This conftest only defines shared steps that
are specific to review tests.
"""

from __future__ import annotations

from pytest_bdd import parsers
from pytest_bdd import when

from brewgis.workspace.models import Workspace
from tests.review.pages.data_catalog_page import DataCatalogPage


# Shared When steps available to all review features
@when(parsers.parse("I navigate to the workspace detail page"))
def navigate_workspace_detail(page, live_server_url) -> None:
    """Navigate to the workspace detail page for the most recently created workspace."""
    ws = Workspace.objects.last()
    assert ws is not None, "No workspace found in database"
    DataCatalogPage(page).navigate(f"{live_server_url}/{ws.pk}/")
