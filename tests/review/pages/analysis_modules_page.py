"""Page object for the workspace detail Analysis Modules panel (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class AnalysisModulesPage(BasePage):
    """UX inspection methods for the workspace detail Analysis Modules panel."""

    def _modules_card_body(self):
        """Return the modules card body locator."""
        return self.page.locator(
            "div.card:has(h5:has-text('Analysis Modules')) div.card-body"
        )

    def module_count(self) -> int:
        """Return the number of module entries in the panel."""
        entries = self._modules_card_body().locator("> div.mb-3")
        return entries.count()

    def get_module_names(self) -> list[str]:
        """Return the list of visible module names."""
        return [
            h6.inner_text().strip()
            for h6 in self._modules_card_body().locator("h6.mb-1").all()
        ]

    def get_module_data(self, module_name: str) -> dict[str, str | list[str]] | None:
        """Return a dict of data for the named module, or None if not found."""
        entry = self._modules_card_body().locator(
            f"> div.mb-3:has(h6:text-is('{module_name}'))"
        )
        if entry.count() == 0:
            return None

        result: dict[str, str | list[str]] = {"name": module_name}

        badge = entry.locator("span.badge")
        if badge.count() > 0:
            result["status"] = badge.inner_text().strip()

        desc = entry.locator("p.text-muted.small.mb-2")
        if desc.count() > 0:
            result["description"] = desc.inner_text().strip()

        for section in entry.locator("div.row.small > div").all():
            strong = section.locator("strong")
            if strong.count() > 0:
                label = strong.inner_text().strip().rstrip(":")
                items = [
                    li.inner_text().strip() for li in section.locator("ul li").all()
                ]
                result[label.lower()] = items

        return result

    def module_status(self, module_name: str) -> str:
        """Return the status badge text for the given module."""
        data = self.get_module_data(module_name)
        if data is None:
            return ""
        return str(data.get("status", ""))

    def has_empty_message(self) -> bool:
        """Check if the modules panel shows 'No analysis modules available'."""
        return self.page.locator("text=No analysis modules available").is_visible()
