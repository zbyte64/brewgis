"""Step definitions for GIS file upload feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import scenarios
from pytest_bdd import when

from tests.e2e.pages.upload_page import UploadPage
from tests.e2e.steps.common_steps import *  # noqa: F403

if TYPE_CHECKING:
    from playwright.sync_api import Page

scenarios(str(Path(__file__).parent.parent / "features" / "upload.feature"))


@when("I navigate to the upload page")
def navigate_upload(page: Page, live_server_url: str) -> None:
    """Navigate to the GIS file upload page."""
    UploadPage(page, live_server_url).navigate_to()


@when("I submit the form without a file")
def submit_empty_upload(page: Page, live_server_url: str) -> None:
    """Submit the upload form with no file selected."""
    UploadPage(page, live_server_url).submit_empty()
