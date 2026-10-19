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

    # ── Paint mode toggle ───────────────────────────────────

    def click_paint_mode(self) -> None:
        """Click the Paint Mode toggle button."""
        self.page.locator("#toggle-paint-btn").click()

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

    # ── Paint controls ──────────────────────────────────────

    # ── Paint result ────────────────────────────────────────

    # ── Map component ───────────────────────────────────────
