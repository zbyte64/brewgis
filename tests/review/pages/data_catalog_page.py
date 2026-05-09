"""Page object for the workspace detail Data Catalog panel (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class DataCatalogPage(BasePage):
    """UX inspection methods for the workspace detail Data Catalog table."""

    def _catalog_table(self):
        """Return the catalog table body locator."""
        return self.page.locator(
            "div.card:has(h5:has-text('Data Catalog')) table tbody"
        )

    def category_count(self) -> int:
        """Return the number of accordion items (categories) in the catalog."""
        return self.page.locator(
            "div.card:has(h5:has-text('Data Catalog')) .accordion-item"
        ).count()

    def get_source_rows(self) -> list[dict[str, str]]:
        """Return list of {source_name, description, status} dicts for catalog rows.
        Iterates across all accordion sections to find all source rows.
        """
        result: list[dict[str, str]] = []
        accordion_items = self.page.locator(
            "div.card:has(h5:has-text('Data Catalog')) .accordion-item"
        )
        for i in range(accordion_items.count()):
            tbody = accordion_items.nth(i).locator("table tbody")
            if tbody.count() == 0:
                continue
            rows = tbody.locator("tr")
            for j in range(rows.count()):
                cells = rows.nth(j).locator("td")
                if cells.count() >= 5:
                    result.append(
                        {
                            "source_name": cells.nth(0).text_content().strip().split("\n")[0].strip(),
                            "description": cells.nth(1).text_content().strip(),
                            "status": cells.nth(4).text_content().strip(),
                        }
                    )
        return result

    def source_count(self) -> int:
        """Return the number of rows in the data catalog table."""
        return self._catalog_table().locator("tr").count()

    def source_status(self, source_name: str) -> str:
        """Return status badge text for a given source name."""
        row = self._catalog_table().locator(
            f"tr:has(td:text-is('{source_name}'))"
        )
        if row.count() == 0:
            return ""
        cells = row.locator("td")
        if cells.count() < 3:
            return ""
        return cells.nth(2).inner_text().strip()

    def catalog_card_is_present(self) -> bool:
        """Check that the Data Catalog card header is visible."""
        return self.page.locator("h5:has-text('Data Catalog')").is_visible()

    def has_quick_action_bar(self) -> bool:
        """Check the quick-action button bar is present on the workspace detail page."""
        return self.page.locator(".d-flex.gap-2.mb-4").is_visible()

    def quick_action_labels(self) -> list[str]:
        """Return the visible quick-action button labels."""
        bar = self.page.locator(".d-flex.gap-2.mb-4")
        return [btn.inner_text().strip() for btn in bar.locator("a, button").all()]
