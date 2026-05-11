"""Step definitions for Data Catalog feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then

from brewgis.workspace.models import Workspace
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.data_catalog_page import DataCatalogPage

scenarios(str(Path(__file__).parent.parent / "features" / "data_catalog.feature"))


@then(parsers.parse("the Data Catalog table should have {count} source rows"))
def catalog_has_source_rows(page, count: str) -> None:
    """Check the data catalog table row count."""
    count = int(count)
    catalog = DataCatalogPage(page)
    assert catalog.source_count() == count, (
        f"Expected {count} source rows, got {catalog.source_count()}"
    )


@then(parsers.parse("the Data Catalog should have {count} source categories"))
def catalog_has_categories(page, count: str) -> None:
    """Check the data catalog accordion item count matches expected categories."""
    count = int(count)
    catalog = DataCatalogPage(page)
    assert catalog.category_count() == count, (
        f"Expected {count} source categories, got {catalog.category_count()}"
    )


@then(parsers.parse('the Data Catalog should list "{name}"'))
def catalog_lists_source(page, name: str) -> None:
    """Check a specific source appears in the catalog."""
    rows = DataCatalogPage(page).get_source_rows()
    source_names = [r["source_name"] for r in rows]
    assert name in source_names, (
        f"Expected '{name}' in catalog sources, got {source_names}"
    )


@then(parsers.parse("the Data Catalog table should have columns {columns}"))
def catalog_has_columns(page, columns: str) -> None:
    """Check the table header columns match expected."""
    data_catalog = page.locator("div.card:has(h5:has-text('Data Catalog'))")
    # Get first table headers (use text_content to read DOM regardless of accordion visibility)
    first_table = data_catalog.locator("table").first
    headers = first_table.locator("thead tr th")
    header_texts = [h.text_content().strip() for h in headers.all()]
    expected = [c.strip().strip('"') for c in columns.split(",")]
    for col in expected:
        assert col in header_texts, (
            f"Expected column '{col}' in header, got {header_texts}"
        )


@then(parsers.parse('all sources should show status "{status}"'))
def catalog_all_status(page, status: str) -> None:
    """Check every source row shows the given status."""
    rows = DataCatalogPage(page).get_source_rows()
    for row in rows:
        assert row["status"] == status, (
            f"Expected source '{row['source_name']}' to have status "
            f"'{status}', got '{row['status']}'"
        )


@then(parsers.parse("I should see a quick-action bar with {buttons}"))
def quick_action_bar(page, buttons: str) -> None:
    """Check the quick-action buttons match expected labels."""
    catalog = DataCatalogPage(page)
    labels = catalog.quick_action_labels()
    expected = [b.strip().strip('"') for b in buttons.split(",")]
    for btn in expected:
        assert btn in labels, f"Expected quick-action '{btn}' in bar, got {labels}"


@then("the workspace name appears in the page heading")
def workspace_name_in_title(page) -> None:
    """Check the workspace name appears in the page title."""
    ws = Workspace.objects.last()
    assert ws is not None
    title = page.title()
    assert ws.name in title, f"Expected '{ws.name}' in page title, got '{title}'"


@then("I should see the workspace name in the page header")
def workspace_name_in_header(page) -> None:
    """Check the workspace name appears in the h1 header."""
    ws = Workspace.objects.last()
    assert ws is not None
    header = page.locator("h1")
    assert header.is_visible(), "Expected h1 header to be visible"
    header_text = header.inner_text().strip()
    assert ws.name in header_text, (
        f"Expected '{ws.name}' in header, got '{header_text}'"
    )


@then("the Data Catalog should show empty state")
def catalog_empty_state(page) -> None:
    """Check that the Data Catalog shows the empty state message."""
    empty = page.locator("div.card:has(h5:has-text('Data Catalog'))").locator(
        "text=No data sources configured."
    )
    assert empty.is_visible(), "Expected empty state: 'No data sources configured.'"


@then("the Data Catalog should have an import data link")
def catalog_import_link(page) -> None:
    """Check the empty state has an Import Data link."""
    catalog_card = page.locator("div.card:has(h5:has-text('Data Catalog'))")
    link = catalog_card.locator("a:has-text('Import Data')")
    assert link.is_visible(), "Expected Import Data link in Data Catalog empty state"
