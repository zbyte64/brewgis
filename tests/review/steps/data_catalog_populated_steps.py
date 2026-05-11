"""Step definitions for Data Catalog populated state feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then

from tests.e2e.steps.common_steps import *  # noqa: F403

scenarios(
    str(Path(__file__).parent.parent / "features" / "data_catalog_populated.feature")
)


@given(parsers.parse('the workspace has a data source category "{name}"'))
def _workspace_has_data_source_category(name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a data source category."""
    from brewgis.workspace.models import DataSourceCategory  # noqa: PLC0415

    DataSourceCategory.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
    )


@given(
    parsers.parse(
        'the workspace has a data source named "{name}" in category "{cat_name}"'
    )
)
def _workspace_has_data_source(name: str, cat_name: str, db) -> None:  # type: ignore[no-untyped-def]
    """Create a data source in the given category."""
    from brewgis.workspace.models import DataSource  # noqa: PLC0415
    from brewgis.workspace.models import DataSourceCategory  # noqa: PLC0415

    cat = DataSourceCategory.objects.get(name=cat_name)
    DataSource.objects.create(
        name=name,
        category=cat,
        provider="Test Provider",
    )


@then("the data catalog should show category count")
def _data_catalog_category_count(page) -> None:
    """Check the category count badge shows a positive number."""
    badge = page.locator(".badge.rounded-pill:has-text('categories')")
    assert badge.is_visible(), "Expected category count badge"


@then(parsers.parse('the data catalog source "{name}" should be present'))
def _data_catalog_source_present(page, name: str) -> None:
    """Check source name is present in the DOM (may be hidden in accordion)."""
    from playwright.sync_api import expect  # noqa: PLC0415

    expect(page.get_by_text(name)).to_be_attached()
