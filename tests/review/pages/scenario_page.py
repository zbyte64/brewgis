"""Page object for workspace Scenario Management panel (UX inspection)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ScenarioPage(BasePage):
    """UX inspection methods for workspace scenario management."""

    def __init__(self, page: Page) -> None:
        super().__init__(page)

    def has_scenario_table(self) -> bool:
        """Check if the scenario table is visible on the workspace detail page."""
        table = self.page.locator(".card:has(h5:has-text('Scenarios')) table")
        return table.is_visible()

    def get_scenario_names(self) -> list[str]:
        """Return the list of scenario names from the scenario table rows."""
        rows = self.page.locator(".card:has(h5:has-text('Scenarios')) table tbody tr")
        names: list[str] = []
        for i in range(rows.count()):
            # The first td contains the scenario name (with badge and strong)
            name_cell = rows.nth(i).locator("td").first
            name_text = name_cell.inner_text().strip()
            names.append(name_text)
        return names

    def has_scenario_action_buttons(self) -> bool:
        """Check for View and Edit action buttons in scenario table rows."""
        actions = self.page.locator(
            ".card:has(h5:has-text('Scenarios')) table tbody tr td:last-child"
        )
        if actions.count() == 0:
            return False
        has_view = False
        has_edit = False
        for i in range(actions.count()):
            cell_text = actions.nth(i).inner_text()
            if "View" in cell_text:
                has_view = True
            if "Edit" in cell_text:
                has_edit = True
        return has_view and has_edit

    def has_scenario_empty_state(self) -> bool:
        """Check for the empty state message in the Scenarios panel."""
        empty = self.page.locator(".card:has(h5:has-text('Scenarios'))")
        return empty.get_by_text("No scenarios yet").is_visible()

    def has_create_base_button(self) -> bool:
        """Check for the 'Create Base Scenario' button in the empty state."""
        button = self.page.locator(".card:has(h5:has-text('Scenarios'))")
        return button.get_by_role("link", name="Create Base Scenario").is_visible()

    def has_scenario_form_fields(self) -> bool:
        """Check that the scenario create form has all required fields."""
        fields = ["name", "base_year", "horizon_year", "scenario_type"]
        for field in fields:
            locator = self.page.locator(f"#id_{field}")
            if not locator.is_visible():
                return False
        return True
