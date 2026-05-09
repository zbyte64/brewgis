"""Page object for the workspace creation page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page  # noqa: F401



class WorkspaceCreationPage(BasePage):
    """Page object for the workspace creation form."""

    def navigate_to(self, live_server_url: str) -> None:
        """Navigate to the create workspace page."""
        self.page.goto(live_server_url + "/new/", wait_until="networkidle")
