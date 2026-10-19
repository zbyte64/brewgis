"""Page object for the Import Center (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class ImportCenterPage(BasePage):
    """UX inspection methods for the Import Center page."""

    IMPORT_CENTER_PATH = "/import/"

    def navigate_to(self, live_server_url: str) -> None:
        """Navigate to the import center page."""
        self.navigate(f"{live_server_url}{self.IMPORT_CENTER_PATH}")

    def tab_labels(self) -> list[str]:
        """Return labels of all import tabs."""
        tabs = self.page.locator("#importTabs button.nav-link")
        return [tab.inner_text().strip() for tab in tabs.all()]

    def has_breadcrumb(self) -> bool:
        """Check if breadcrumb navigation is present."""
        return self.page.locator("nav[aria-label='breadcrumb']").is_visible()

    def breadcrumb_path(self) -> list[str]:
        """Return the breadcrumb trail as a list of labels."""
        items = self.page.locator("nav[aria-label='breadcrumb'] ol li")
        return [item.inner_text().strip() for item in items.all()]

    def page_title_text(self) -> str:
        """Return the page heading text."""
        h2 = self.page.locator("h2")
        if h2.count() > 0:
            return h2.inner_text().strip()
        return ""

    def tab_id_for_label(self, label: str) -> str | None:
        """Map a tab button label to its content pane id."""
        mapping = {
            "Upload File": "upload",
            "Points of Interest": "poi",
            "Census Data": "census",
            "Stitch & Fill": "stitch",
        }
        tab = mapping.get(label)
        if tab:
            return tab
        # Try matching sub-tab labels
        sub_mapping = {
            "ACS Demographics": "census-acs",
            "LEHD Employment": "census-lehd",
            "Spatial Allocation": "allocate",
            "Column Stitching": "impute",
        }
        return sub_mapping.get(label)
