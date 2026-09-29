"""Page object for the Built Forms panel (UX inspection)."""

from __future__ import annotations

from tests.e2e.pages.base_page import BasePage


class BuiltFormsPage(BasePage):
    """UX inspection methods for the map's Built Forms panel.

    The library has no page of its own: both lists render in the map shell's
    left sidebar, and the create/edit forms open in the map's right-hand
    drawer (``?panel=built-forms`` opens that tab on load).
    """

    BODY = "#built-forms-body"
    ROWS = f"{BODY} [data-building-type-pk], {BODY} [data-place-type-pk]"

    def _open_panel(self, live_server_url: str, workspace_pk: int) -> None:
        self.navigate(f"{live_server_url}/{workspace_pk}/map/?panel=built-forms")
        self.page.locator(self.BODY).wait_for(state="visible", timeout=15000)

    def navigate_to_building_types(
        self, live_server_url: str, workspace_pk: int
    ) -> None:
        """Open the map with the Built Forms panel showing."""
        self._open_panel(live_server_url, workspace_pk)

    def navigate_to_place_types(self, live_server_url: str, workspace_pk: int) -> None:
        """Open the map with the Built Forms panel showing.

        Both libraries share one panel, so this is the same surface as
        ``navigate_to_building_types`` — kept as its own method so the
        feature files can read as one scenario per library.
        """
        self._open_panel(live_server_url, workspace_pk)

    def row_count(self) -> int:
        """Return the number of built form rows visible."""
        return self.page.locator(self.ROWS).count()

    def row_titles(self) -> list[str]:
        """Return the names of every built form row, stripped of quotes."""
        titles: list[str] = []
        for row in self.page.locator(self.ROWS).all():
            name_button = row.locator("button").first
            if name_button.count() > 0:
                titles.append(name_button.inner_text().strip().strip('"'))
        return titles

    def has_create_button(self) -> bool:
        """Check that the panel offers both create actions."""
        return (
            self.page.locator("#new-building-type-btn").is_visible()
            and self.page.locator("#new-place-type-btn").is_visible()
        )

    def every_row_has_actions(self) -> bool:
        """Check that each row offers an edit and a delete control.

        Each row is a name button (opens the drawer) plus a delete button.
        """
        rows = self.page.locator(self.ROWS).all()
        if not rows:
            return False
        return all(row.locator("button").count() >= 2 for row in rows)
