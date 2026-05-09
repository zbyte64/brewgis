"""Page object for the Layer Groups panel (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class LayerGroupsPage(BasePage):
    """UX inspection methods for the layer groups panel on the workspace map page."""

    LAYER_GROUP_LIST_SELECTOR = "#layer-group-list"

    def navigate_to_map(self, workspace_pk: int, live_server_url: str) -> None:
        """Navigate to the workspace map page and trigger the layer groups panel load."""
        self.navigate(f"{live_server_url}/{workspace_pk}/map/")
        # Click the Groups button to trigger htmx load of the layer groups panel
        groups_btn = self.page.get_by_title("Layer Groups")
        groups_btn.click()
        # Wait for htmx to load the partial content
        self.page.wait_for_selector(self.LAYER_GROUP_LIST_SELECTOR, timeout=5000)

    def has_layer_groups_panel(self) -> bool:
        """Check if the layer groups panel is visible on the page.

        The panel root element is loaded into #layer-group-container after htmx
        swaps the partial into place.  We check for the rendered content wrapper
        or the heading text.
        """
        locator = self.page.locator(self.LAYER_GROUP_LIST_SELECTOR)
        if not locator.is_visible():
            return False
        # Confirm the heading label rendered inside the partial
        heading = locator.get_by_text("Layer Groups", exact=False)
        return heading.is_visible()

    def has_empty_state(self) -> bool:
        """Check if the layer groups panel shows the empty state message.

        Returns True when either:
        - The text "No layers or groups yet" is visible inside the panel
        - The panel is present but empty (children are minimal / placeholder)
        """
        locator = self.page.locator(self.LAYER_GROUP_LIST_SELECTOR)
        if not locator.is_visible():
            return False
        empty = locator.get_by_text("No layers or groups yet", exact=False)
        return empty.is_visible()
