"""Page object for the GIS file upload page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class UploadPage(BasePage):
    """Page object for the GIS file upload form."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to(self) -> None:
        """Navigate to the upload page."""
        self.navigate(self.base_url + "/upload/")

    def submit_empty(self) -> None:
        """Submit the form without any file selected.

        Disables HTML5 constraint validation first — otherwise the browser
        blocks the empty submit client-side and the request never reaches
        the server, so the server-side validation error would never render.
        """
        self.page.evaluate("document.querySelector('form').noValidate = true")
        self.page.click("button[type=submit]")
