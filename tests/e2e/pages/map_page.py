"""Page object for the workspace map page with paint interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class MapPage(BasePage):
    """Page object for the workspace map page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page)
        self.base_url = base_url

    def navigate_to(self, workspace_pk: int, scenario_pk: int | None = None) -> None:
        """Navigate to the map page, optionally with a scenario selected."""
        url = f"{self.base_url}/{workspace_pk}/map/"
        if scenario_pk is not None:
            url += f"?scenario={scenario_pk}"
        self.navigate(url)

    # ── Scenario selection ──────────────────────────────────

    def select_scenario_by_value(self, scenario_pk: int) -> None:
        """Select a scenario from the dropdown by its PK value."""
        self.page.select_option('select[name="scenario"]', str(scenario_pk))

    def get_scenario_dropdown(self) -> object:
        """Return the scenario select element."""
        return self.page.locator('select[name="scenario"]')

    def is_scenario_dropdown_visible(self) -> bool:
        """Check if the scenario dropdown is visible."""
        return self.page.locator('select[name="scenario"]').is_visible()

    # ── Paint mode toggle ───────────────────────────────────

    def click_paint_mode(self) -> None:
        """Click the Paint Mode toggle button."""
        self.page.locator("#toggle-paint-btn").click()

    def get_paint_toggle_text(self) -> str:
        """Get the text of the paint mode toggle button."""
        return self.page.locator("#toggle-paint-btn").text_content() or ""

    def is_paint_toolbar_visible(self) -> bool:
        """Check if the paint toolbar is visible."""
        toolbar = self.page.locator("#paint-toolbar")
        return toolbar.is_visible()

    # ── Feature selection simulation ────────────────────────

    def set_selected_features(self, feature_ids: list[str]) -> None:
        """Simulate feature selection by dispatching a custom event.

        This mimics what MapLibre-gl-draw does when features are selected.
        """
        self.page.evaluate(
            """
            (ids) => {
                const map = document.querySelector('brew-gis-map');
                if (!map) return;
                const input = document.getElementById('paint-feature-ids');
                if (input) input.value = JSON.stringify(ids);
                const count = document.getElementById('paint-feature-count');
                if (count) count.textContent = ids.length + ' parcel(s) selected';
                const apply = document.getElementById('paint-apply-btn');
                const clear = document.getElementById('paint-clear-btn');
                if (apply) apply.disabled = ids.length === 0;
                if (clear) clear.disabled = ids.length === 0;
                // Dispatch the event so htmx picks up the change
                map.dispatchEvent(new CustomEvent('paint-features-changed', {
                    detail: { features: ids.map(id => ({ id, layerId: '' })), mode: 'select' },
                    bubbles: true,
                    composed: true,
                }));
            }
            """,
            feature_ids,
        )

    def get_feature_count_text(self) -> str:
        """Get the feature count display text."""
        return self.page.locator("#paint-feature-count").text_content() or ""

    # ── Paint controls ──────────────────────────────────────

    def select_column(self, column_name: str) -> None:
        """Select a column from the paint column dropdown."""
        self.page.select_option("#paint-column", column_name)

    def fill_value(self, value: str) -> None:
        """Enter a paint value."""
        self.page.fill("#paint-value", value)

    def click_apply(self) -> None:
        """Click the Apply button."""
        self.page.locator("#paint-apply-btn").click()

    def click_clear(self) -> None:
        """Click the Clear button."""
        self.page.locator("#paint-clear-btn").click()

    def is_apply_disabled(self) -> bool:
        """Check if the Apply button is disabled."""
        return self.page.locator("#paint-apply-btn").is_disabled()

    def is_clear_disabled(self) -> bool:
        """Check if the Clear button is disabled."""
        return self.page.locator("#paint-clear-btn").is_disabled()

    # ── Paint result ────────────────────────────────────────

    def get_result_text(self) -> str:
        """Get the text from the paint result area."""
        result = self.page.locator("#paint-result")
        if result.is_visible():
            return result.text_content() or ""
        return ""

    def is_result_success(self) -> bool:
        """Check if the result shows a success message."""
        return self.page.locator("#paint-result .alert-success").is_visible()

    def wait_for_paint_response(self, timeout: int = 5000) -> None:
        """Wait for the paint operation to complete and result to appear."""
        self.page.wait_for_selector(
            "#paint-result .alert-success, #paint-result .alert-danger",
            timeout=timeout,
        )

    # ── Map component ───────────────────────────────────────

    def get_map_mode(self) -> str | None:
        """Get the current mode of the brew-gis-map component."""
        return self.page.evaluate(
            "document.querySelector('brew-gis-map')?.getAttribute('mode')"
        )

    def get_map_scenario_id(self) -> str | None:
        """Get the scenario-id attribute of the map component."""
        return self.page.evaluate(
            "document.querySelector('brew-gis-map')?.getAttribute('scenario-id')"
        )
