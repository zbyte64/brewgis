"""Page object for the workspace map page (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class MapReviewPage(BasePage):
    """UX inspection methods for the workspace map page."""

    def map_component_is_visible(self) -> bool:
        """Check the brew-gis-map web component is rendered."""
        return self.page.locator("brew-gis-map").is_visible()

    def scenario_dropdown_is_visible(self) -> bool:
        """Check the scenario selector dropdown is present."""
        return (
            self.page.locator(
                "select[name='scenario'], select#scenario-select, select.scenario-select"
            )
            .first.is_visible()
        )

    def paint_toolbar_is_present(self) -> bool:
        """Check the paint toolbar section exists."""
        return self.page.locator(
            "#paint-toolbar, .paint-toolbar, [data-testid='paint-toolbar']"
        ).first.is_visible()

    def undo_redo_buttons_present(self) -> bool:
        """Check undo/redo buttons are visible in the paint toolbar."""
        undo = self.page.get_by_role("button", name="Undo").is_visible()
        redo = self.page.get_by_role("button", name="Redo").is_visible()
        return undo or redo

    def layer_list_visible(self) -> bool:
        """Check the layer list/panel is visible."""
        return self.page.locator("#layer-list, .layer-list, [data-testid='layer-list']").first.is_visible()

    def built_forms_dropdown_visible(self) -> bool:
        """Check the built forms dropdown (building/place type selector) is visible."""
        return self.page.locator(
            "select#built-form-select, select[name='built_form'], "
            "optgroup[label='Building Types']"
        ).first.is_visible()

    def navigate_to_map(self, workspace_pk: int, live_server_url: str) -> None:
        """Navigate to the map page for the given workspace."""
        self.navigate(f"{live_server_url}/{workspace_pk}/map/")

    def has_back_button(self) -> bool:
        """Check if a back navigation link is visible."""
        return self.page.get_by_role("link", name="Back").is_visible()
