"""Step definitions for Import Center feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.review.pages.import_center_page import ImportCenterPage
from tests.e2e.steps.common_steps import *  # noqa: F403

scenarios(str(Path(__file__).parent.parent / "features" / "import_center.feature"))


@when("I navigate to the import center")
def navigate_import_center(page, live_server_url) -> None:
    """Navigate to the import center page."""
    ImportCenterPage(page).navigate_to(live_server_url)


@then(parsers.parse("I should see import tabs {tab_list}"))
def see_import_tabs(page, tab_list: str) -> None:
    """Check all expected tabs are present."""
    expected = [t.strip('"') for t in tab_list.split(",")]
    labels = ImportCenterPage(page).tab_labels()
    for tab in expected:
        assert tab in labels, (
            f"Expected tab '{tab}' in import center, got {labels}"
        )


@then(parsers.parse('the page title should be "{title}"'))
def page_title_is(page, title: str) -> None:
    """Check the page h2 heading matches."""
    actual = ImportCenterPage(page).page_title_text()
    assert actual == title, (
        f"Expected page title '{title}', got '{actual}'"
    )


@then("I should see a breadcrumb")
def see_breadcrumb(page) -> None:
    """Check breadcrumb is present."""
    assert ImportCenterPage(page).has_breadcrumb(), "Expected breadcrumb to be visible"


@then(parsers.parse("the breadcrumb should show {crumbs}"))
def breadcrumb_shows(page, crumbs: str) -> None:
    """Check breadcrumb path."""
    expected = [c.strip('"') for c in crumbs.split(",")]
    path = ImportCenterPage(page).breadcrumb_path()
    for crumb in expected:
        assert crumb in path, (
            f"Expected breadcrumb '{crumb}' in path, got {path}"
        )


@then(parsers.parse('the "{tab}" tab should contain "{text}"'))
def tab_contains_text(page, tab: str, text: str) -> None:
    """Check a tab pane contains the given text."""
    tab_id = ImportCenterPage(page).tab_id_for_label(tab)
    assert tab_id is not None, f"Unknown tab '{tab}'"
    pane = page.locator(f"#{tab_id}")
    pane_text = pane.inner_text()
    assert text in pane_text, (
        f"Expected text '{text}' in tab '{tab}', got:\n{pane_text}"
    )


@then(parsers.parse('the "{tab}" tab should have an "{link_text}" link'))
def tab_has_link(page, tab: str, link_text: str) -> None:
    """Check a tab pane contains a link with the given text."""
    tab_id = ImportCenterPage(page).tab_id_for_label(tab)
    assert tab_id is not None, f"Unknown tab '{tab}'"
    link = page.locator(f"#{tab_id}").get_by_role("link", name=link_text)
    assert link.is_visible(), (
        f"Expected link '{link_text}' in tab '{tab}'"
    )


@then(parsers.parse('the "{tab}" tab should have sub-tabs {sub_tabs}'))
def tab_has_sub_tabs(page, tab: str, sub_tabs: str) -> None:
    """Check a tab pane contains the expected sub-tabs."""
    tab_id = ImportCenterPage(page).tab_id_for_label(tab)
    assert tab_id is not None, f"Unknown tab '{tab}'"
    expected = [s.strip('"') for s in sub_tabs.split(",")]
    sub_buttons = page.locator(f"#{tab_id} ul.nav-pills button.nav-link")
    labels = [b.inner_text().strip() for b in sub_buttons.all()]
    for sub in expected:
        assert sub in labels, (
            f"Expected sub-tab '{sub}' in tab '{tab}', got {labels}"
        )
