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

    def has_file_field(self) -> bool:
        """Check if the file upload field is present."""
        return self.page.locator("input[type=file]").is_visible()

    def submit_empty(self) -> None:
        """Submit the form without any file selected."""
        self.page.click("button[type=submit]")

    def get_validation_errors(self) -> list[str]:
        """Get validation error messages."""
        errors = self.page.locator(".invalid-feedback, .alert-danger, .errorlist")
        return [e.text_content() or "" for e in errors.all() if e.is_visible()]
