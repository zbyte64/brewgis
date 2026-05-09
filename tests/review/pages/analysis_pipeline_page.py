"""Page object for Analysis Pipeline pages (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class AnalysisPipelinePage(BasePage):
    """UX inspection methods for analysis pipeline pages (launch, list, status)."""

    def navigate_to_launch(self, live_server_url: str) -> None:
        """Navigate to the analysis launch page."""
        self.navigate(f"{live_server_url}/workspace/analysis/launch/")

    def navigate_to_list(self, live_server_url: str) -> None:
        """Navigate to the analysis runs list page."""
        self.navigate(f"{live_server_url}/workspace/analysis/")

    def launch_form_fields(self) -> list[str]:
        """Return labels of all form fields on the launch page."""
        fields: list[str] = []
        for label in self.page.locator("label").all():
            text = label.inner_text().strip()
            if text:
                fields.append(text)
        return fields

    def has_new_run_button(self) -> bool:
        """Check if the 'New Run' button is present on the list page."""
        return self.page.get_by_role("link", name="New Run").is_visible()

    def run_count(self) -> int:
        """Return the number of analysis runs listed."""
        return self.page.locator("table tbody tr").count()

    def has_empty_message(self) -> bool:
        """Check if the list shows 'No analysis runs yet'."""
        return self.page.locator("text=No analysis runs yet").is_visible()

    def status_badges(self) -> list[str]:
        """Return the visible status badge texts on the list page."""
        badges: list[str] = []
        for badge in self.page.locator("table tbody tr td span.badge").all():
            badges.append(badge.inner_text().strip())
        return badges
