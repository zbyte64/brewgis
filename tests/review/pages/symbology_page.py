"""Page object for the Symbology Editor page (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class SymbologyPage(BasePage):
    """UX inspection methods for the symbology editor."""

    def navigate_to_symbology(self, layer_pk: int, live_server_url: str) -> None:
        """Navigate to the symbology editor for the given layer."""
        self.navigate(f"{live_server_url}/symbology/{layer_pk}/edit/")

    def symbology_type_options(self) -> list[str]:
        """Return the available symbology type options."""
        select = self.page.locator("select[name='symbology_type']")
        return [
            opt.inner_text().strip()
            for opt in select.locator("option").all()
        ]

    def selected_symbology_type(self) -> str:
        """Return the currently selected symbology type."""
        select = self.page.locator("select[name='symbology_type']")
        return select.input_value()

    def has_color_controls(self) -> bool:
        """Check if color inputs are present (default color, stroke color)."""
        return (
            self.page.locator("input[type='color']").count() >= 2
        )

    def has_editor_form(self) -> bool:
        """Check if the symbology edit form is present."""
        return self.page.locator("form[hx-post='.']").is_visible()

    def has_save_button(self) -> bool:
        """Check if the Save Symbology button is present."""
        return self.page.get_by_role("button", name="Save Symbology").is_visible()

    def has_auto_generate_button(self) -> bool:
        """Check if the Auto-Generate button is present."""
        return self.page.get_by_role("button", name="Auto").is_visible()

    def style_class_count(self) -> int:
        """Return the number of style class rows in the table."""
        return self.page.locator("table input[name='class_label[]']").count()

    def page_title_text(self) -> str:
        """Return the page title (h5 in card header)."""
        el = self.page.locator("div.card-header h5.card-title")
        if el.count() > 0:
            return el.inner_text().strip()
        return ""
